"""PackageContextCompiler — deterministic ContextPackage from composed sections (ADR-007).

Same inputs produce byte-identical packages. The trust level is the minimum of
included content (LLM proposals lower it to PROPOSED); budget drops become the
package's ``degraded`` sections; an insufficient composition overrides the
quality state so consumers fail closed.
"""
from dataclasses import replace

from datahek.contracts.context import (
    ArtifactEnvelope,
    ArtifactKind,
    CapabilityContext,
    ComposedContext,
    ContextBudget,
    ContextPackage,
    GovernanceContext,
    ProvenanceSource,
    QualityState,
    SemanticsSummary,
    TrustLevel,
    ValidationStatus,
)
from datahek.context.provenance import effective_trust


def _default_governance() -> GovernanceContext:
    return GovernanceContext(
        envelope=ArtifactEnvelope(
            kind=ArtifactKind.GOVERNANCE, schema_version=1,
            provenance=ProvenanceSource.SYSTEM, trust=TrustLevel.SYSTEM,
            validation=ValidationStatus.NOT_REQUIRED, confidence=1.0,
            generated_at=""),
        sensitive_columns=(), restricted_columns=(), allowed_operations=("SELECT",),
        masking_policy_refs=(), permission_version="oss:local")


def _capability_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope(
        kind=ArtifactKind.CAPABILITY, schema_version=1,
        provenance=ProvenanceSource.SYSTEM, trust=TrustLevel.SYSTEM,
        validation=ValidationStatus.NOT_REQUIRED, confidence=1.0, generated_at="")


def _semantics(composed: ComposedContext) -> SemanticsSummary:
    dimensions: list[str] = []
    identifiers: list[str] = []
    temporal: list[str] = []
    if composed.taxonomy is not None:
        for node in composed.taxonomy.nodes:
            if node.node_kind != "category":
                continue
            category = node.path[-1]
            if category == "Dimension":
                dimensions.extend(node.members)
            elif category == "Identifier":
                identifiers.extend(node.members)
            elif category == "Temporal":
                temporal.extend(node.members)
    if not (dimensions or identifiers or temporal) and composed.profiles:
        for table, columns in composed.profiles.items():
            for column in columns:
                member = f"{table}.{column.name}"
                if "identifier" in column.role_candidates:
                    identifiers.append(member)
                if "dimension" in column.role_candidates:
                    dimensions.append(member)
                if "temporal" in column.role_candidates:
                    temporal.append(member)
    return SemanticsSummary(
        metrics=tuple(composed.metrics),
        dimensions=tuple(sorted(set(dimensions))),
        identifiers=tuple(sorted(set(identifiers))),
        temporal_fields=tuple(sorted(set(temporal))))


def _trust_floor(composed: ComposedContext, governance: GovernanceContext) -> TrustLevel:
    trusts = [governance.envelope.trust, TrustLevel.STRUCTURAL]
    for artifact in (composed.topology, composed.granularity, composed.taxonomy,
                     composed.ontology):
        if artifact is not None:
            trusts.append(artifact.envelope.trust)
    return effective_trust(trusts)


class PackageContextCompiler:
    async def compile(self, ctx, composed: ComposedContext, *, quality, freshness,
                      governance: GovernanceContext | None = None,
                      skills: tuple = (), tools: tuple = (),
                      providers: tuple = ()) -> ContextPackage:
        active_governance = governance or composed.governance or _default_governance()
        if composed.insufficient_reason:
            quality = replace(
                quality, state=QualityState.INSUFFICIENT,
                details={**quality.details,
                         "insufficient_reason": composed.insufficient_reason})
        return ContextPackage(
            context_id=composed.context_id, org_id=ctx.organization_id,
            project_id=ctx.project_id, connection_id=composed.connection_id,
            version=composed.version, schema_hash=composed.schema_hash,
            purpose=composed.purpose, generated_at=freshness.refresh_due_at or "",
            schema=composed.schema,
            profile={table: tuple(columns)
                     for table, columns in sorted(composed.profiles.items())},
            taxonomy=composed.taxonomy.nodes if composed.taxonomy is not None else (),
            ontology=(composed.ontology.concepts if composed.ontology is not None else ()),
            topology=(composed.topology.edges if composed.topology is not None else ()),
            granularity=(composed.granularity.grains
                         if composed.granularity is not None else ()),
            semantics=_semantics(composed),
            governance=active_governance,
            capabilities=CapabilityContext(
                envelope=_capability_envelope(), skills=tuple(skills),
                tools=tuple(tools), providers=tuple(providers)),
            quality=quality,
            freshness=freshness,
            trust=_trust_floor(composed, active_governance),
            budget=ContextBudget(tokens_estimate=composed.tokens_estimate,
                                 dropped_sections=composed.dropped),
            degraded=composed.dropped,
        )
