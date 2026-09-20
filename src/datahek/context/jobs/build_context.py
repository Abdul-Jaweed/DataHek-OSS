"""ContextBuildJob — staged orchestration of the context build pipeline.

Stages run in deterministic order: INTROSPECT, PROFILE, TOPOLOGY, GRANULARITY,
TAXONOMY, ENRICH, GRAPH_BUILD, QUALITY, PUBLISH. Introspection failure aborts
without publishing; every other stage degrades with a warning. Transient stage
errors are retried (``max_retries``); an unchanged schema short-circuits with
``state="current"``.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from datahek.context.freshness import evaluate_freshness
from datahek.context.granularity import build_granularity_context
from datahek.context.quality import evaluate_quality
from datahek.context.snapshot import build_schema_context
from datahek.context.taxonomy import build_taxonomy_context
from datahek.context.topology import build_topology_context
from datahek.contracts.context import (
    ArtifactKind,
    FreshnessReport,
    LifecycleState,
    QualityReport,
)
from datahek.kernel.context import RequestContext

_TOPOLOGY_STAGE = "TOPOLOGY"
_GRANULARITY_STAGE = "GRANULARITY"


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    duration_ms: int
    detail: str = ""


@dataclass(frozen=True)
class BuildResult:
    connection_id: str
    state: str
    context_id: str | None = None
    version: int | None = None
    stages: tuple[StageResult, ...] = ()
    quality: QualityReport | None = None
    freshness: FreshnessReport | None = None
    degraded: bool = False
    warnings: tuple[str, ...] = ()


class ContextBuildJob:
    def __init__(self, *, schema_service, registry_service, profiler=None, enricher=None,
                 graph_builder=None, domain: str = "General", max_retries: int = 1):
        self._schema_service = schema_service
        self._registry_service = registry_service
        self._profiler = profiler
        self._enricher = enricher
        self._graph_builder = graph_builder
        self._domain = domain
        self._max_retries = max(0, max_retries)

    async def _stage(self, name: str, factory) -> tuple[object, StageResult]:
        started = time.perf_counter()
        detail = ""
        for _ in range(self._max_retries + 1):
            try:
                value = await factory()
                elapsed = int((time.perf_counter() - started) * 1000)
                return value, StageResult(name, "ok", elapsed)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"[:300]
        elapsed = int((time.perf_counter() - started) * 1000)
        return None, StageResult(name, "failed", elapsed, detail)

    async def run(self, ctx: RequestContext, connection, provider, *, tables=None,
                  metrics=(), enrichment: bool = True,
                  require_validation: bool = False,
                  skip_if_current: bool = True) -> BuildResult:
        stages: list[StageResult] = []
        warnings: list[str] = []
        degraded = False

        catalog, stage = await self._stage(
            "INTROSPECT",
            lambda: self._schema_service.get_catalog(ctx, connection, provider,
                                                     force_refresh=True))
        stages.append(stage)
        if stage.status == "failed":
            return BuildResult(connection_id=connection.id, state="failed", stages=tuple(stages),
                               warnings=(stage.detail,))
        schema = build_schema_context(catalog, database=connection.database or connection.name)

        if skip_if_current and await self._registry_service.is_current(
                ctx, connection_id=connection.id, scope="connection",
                schema_hash=schema.schema_hash):
            return BuildResult(connection_id=connection.id, state="current",
                               stages=tuple(stages))

        profiles = None
        if self._profiler is not None:
            profiles, stage = await self._stage(
                "PROFILE",
                lambda: self._profiler.profile(ctx, connection, catalog, tables=tables))
            if stage.status == "failed":
                stage = StageResult(stage.name, "degraded", stage.duration_ms, stage.detail)
                warnings.append(f"profiling failed: {stage.detail}")
                degraded = True
            stages.append(stage)
        else:
            stages.append(StageResult("PROFILE", "skipped", 0, "no profiler configured"))

        topology, stage = await self._stage(
            _TOPOLOGY_STAGE, lambda: _async_value(build_topology_context(schema)))
        stages.append(stage)

        granularity, stage = await self._stage(
            _GRANULARITY_STAGE,
            lambda: _async_value(build_granularity_context(schema, profiles, metrics=metrics)))
        stages.append(stage)

        taxonomy = None
        if profiles is not None:
            taxonomy, stage = await self._stage(
                "TAXONOMY",
                lambda: _async_value(build_taxonomy_context(profiles, domain=self._domain)))
            stages.append(stage)
        else:
            stages.append(StageResult("TAXONOMY", "skipped", 0, "no profiles available"))

        ontology = None
        if enrichment and self._enricher is not None and taxonomy is not None:
            ontology, stage = await self._stage(
                "ENRICH",
                lambda: self._enricher.propose(schema, taxonomy, metrics=tuple(metrics)))
            if stage.status == "failed":
                stage = StageResult(stage.name, "degraded", stage.duration_ms, stage.detail)
                warnings.append(f"enrichment failed (continuing without proposals): "
                                f"{stage.detail}")
                degraded = True
            elif ontology is not None and ontology.envelope.warnings:
                warnings.extend(ontology.envelope.warnings)
            stages.append(stage)
        else:
            stages.append(StageResult("ENRICH", "skipped", 0, "disabled"))

        if self._graph_builder is not None:
            graph_report, stage = await self._stage(
                "GRAPH_BUILD",
                lambda: self._graph_builder.build(
                    ctx, connection.id, schema=schema, profiles=profiles, topology=topology,
                    taxonomy=taxonomy, granularity=granularity, ontology=ontology,
                    metrics=tuple(metrics)))  # type: ignore[arg-type]
            if graph_report is not None and getattr(graph_report, "degraded", False):
                stage = StageResult(stage.name, "degraded", stage.duration_ms,
                                    "; ".join(getattr(graph_report, "warnings", ())) or
                                    "graph degraded")
                warnings.append("graph projection degraded")
                degraded = True
            elif stage.status == "failed":
                stage = StageResult(stage.name, "degraded", stage.duration_ms, stage.detail)
                warnings.append(f"graph projection failed: {stage.detail}")
                degraded = True
            stages.append(stage)
        else:
            stages.append(StageResult("GRAPH_BUILD", "skipped", 0, "no graph backend"))

        stamp = datetime.now(timezone.utc).isoformat()
        freshness = evaluate_freshness(generated_at=stamp,
                                       artifact_schema_hash=schema.schema_hash)
        quality = evaluate_quality(schema=schema, profiles=profiles, topology=topology,
                                   granularity=granularity, taxonomy=taxonomy,
                                   ontology=ontology, freshness=freshness)
        stages.append(StageResult("QUALITY", "ok", 0, quality.state.value))

        artifacts = {ArtifactKind.SCHEMA: schema}
        if profiles is not None:
            artifacts[ArtifactKind.PROFILE] = profiles
        if topology is not None:
            artifacts[ArtifactKind.TOPOLOGY] = topology
        if granularity is not None:
            artifacts[ArtifactKind.GRANULARITY] = granularity
        if taxonomy is not None:
            artifacts[ArtifactKind.TAXONOMY] = taxonomy
        if ontology is not None:
            artifacts[ArtifactKind.ONTOLOGY] = ontology

        record, stage = await self._stage(
            "PUBLISH",
            lambda: self._registry_service.publish(
                ctx, connection_id=connection.id, scope="connection",
                schema_hash=schema.schema_hash, artifacts=artifacts, quality=quality,
                freshness=freshness, notes="context build", require_validation=require_validation))
        stages.append(stage)
        if record is None:
            return BuildResult(connection_id=connection.id, state="failed", stages=tuple(stages),
                               quality=quality, freshness=freshness, degraded=degraded,
                               warnings=tuple(warnings) + (stage.detail,))

        return BuildResult(
            connection_id=connection.id,
            state=record.state.value,
            context_id=record.context_id,
            version=record.version,
            stages=tuple(stages),
            quality=quality,
            freshness=freshness,
            degraded=degraded,
            warnings=tuple(warnings),
        )


async def _async_value(value):
    return value
