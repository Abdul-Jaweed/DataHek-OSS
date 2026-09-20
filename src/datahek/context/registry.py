"""ContextRegistryService — version allocation, supersede, and invalidation (ADR-006).

Publishing is the only way records enter the registry: it allocates the next
version for the scope, stores artifacts first, registers the record, and marks
the previous ACTIVE record SUPERSEDED. LLM proposals can park a record in
PENDING_VALIDATION when a validation workflow is required; the OSS default
publishes ACTIVE with proposals marked PENDING.
"""
from datetime import datetime, timezone

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    ContextArtifact,
    ContextRecord,
    FreshnessReport,
    LifecycleState,
    ProvenanceSource,
    QualityReport,
)
from datahek.kernel.context import RequestContext
from datahek.kernel.ids import entity_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_proposals(artifacts: dict[ArtifactKind, ContextArtifact]) -> bool:
    return any(artifact.envelope.provenance is ProvenanceSource.LLM
               for artifact in artifacts.values())


class ContextRegistryService:
    def __init__(self, registry, store):
        self._registry = registry
        self._store = store

    async def publish(self, ctx: RequestContext, *, connection_id: str, scope: str,
                      schema_hash: str, artifacts: dict[ArtifactKind, ContextArtifact],
                      quality: QualityReport, freshness: FreshnessReport,
                      notes: str = "", require_validation: bool = False) -> ContextRecord:
        previous = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        version = previous.version + 1 if previous is not None else 1
        target_state = (LifecycleState.PENDING_VALIDATION
                        if require_validation and _has_proposals(artifacts)
                        else LifecycleState.ACTIVE)
        stamp = _now()
        provenance_summary: dict[str, int] = {}
        for artifact in artifacts.values():
            key = artifact.envelope.provenance.value
            provenance_summary[key] = provenance_summary.get(key, 0) + 1
        record = ContextRecord(
            context_id=entity_id("context"),
            org_id=ctx.organization_id,
            project_id=ctx.project_id,
            connection_id=connection_id,
            scope=scope,
            version=version,
            state=LifecycleState.GENERATED,
            schema_hash=schema_hash,
            created_at=stamp,
            updated_at=stamp,
            artifact_kinds=tuple(sorted(artifacts, key=lambda kind: kind.value)),
            quality=quality,
            freshness=freshness,
            previous_version=previous.version if previous is not None else None,
            supersedes=previous.context_id if previous is not None else None,
            provenance_summary=provenance_summary,
            notes=notes,
        )
        await self._registry.register(ctx, record)
        for kind, artifact in artifacts.items():
            await self._store.put(ctx, record.context_id, artifact)
        await self._registry.set_state(ctx, record.context_id, target_state, "published")
        published = await self._registry.get(ctx, record.context_id)
        if previous is not None:
            await self._registry.set_state(
                ctx, previous.context_id, LifecycleState.SUPERSEDED,
                f"superseded by {record.context_id}")
        return published

    async def is_current(self, ctx: RequestContext, *, connection_id: str, scope: str,
                         schema_hash: str) -> bool:
        active = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        return active is not None and active.schema_hash == schema_hash

    async def invalidate(self, ctx: RequestContext, *, connection_id: str,
                         reason: str) -> int:
        return await self._registry.invalidate(ctx, connection_id=connection_id,
                                               reason=reason)

    async def active(self, ctx: RequestContext, *, connection_id: str,
                     scope: str) -> ContextRecord | None:
        return await self._registry.active(ctx, connection_id=connection_id, scope=scope)

    async def active_artifact(self, ctx: RequestContext, *, connection_id: str, scope: str,
                              kind: ArtifactKind) -> ContextArtifact | None:
        active = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        if active is None:
            return None
        return await self._store.get(ctx, active.context_id, kind)
