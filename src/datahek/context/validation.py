"""Human semantic validation — approve, edit, or reject proposed context items (ADR-008).

Decisions address immutable per-version items by ``(kind, section, index)``. Applying
decisions publishes a **new version** whose items carry `HUMAN_VALIDATED` provenance
(approve/edit) or `REJECTED` (reject) — the reviewed version is never mutated.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from datahek.context.freshness import evaluate_freshness
from datahek.context.quality import evaluate_quality
from datahek.contracts.context import (
    ArtifactKind,
    GranularityContext,
    OntologyContext,
    ProvenanceSource,
    TaxonomyContext,
    ValidationStatus,
)
from datahek.kernel.errors import DatahekError, ErrorCode

_ACTIONS = ("approve", "edit", "reject")
_SECTIONS: dict[ArtifactKind, tuple[str, ...]] = {
    ArtifactKind.ONTOLOGY: ("concepts", "relationships"),
    ArtifactKind.TAXONOMY: ("nodes",),
    ArtifactKind.GRANULARITY: ("grains",),
}
_EDITABLE: dict[ArtifactKind, dict[str, set[str]]] = {
    ArtifactKind.ONTOLOGY: {"concepts": {"description", "synonyms"},
                            "relationships": {"predicate"}},
    ArtifactKind.TAXONOMY: {"nodes": set()},
    ArtifactKind.GRANULARITY: {"grains": {"statement", "qualifier", "entity"}},
}
_PROVENANCE_FIELD: dict[ArtifactKind, str] = {ArtifactKind.GRANULARITY: "source"}
_VALIDATED_STATUSES = (ValidationStatus.APPROVED, ValidationStatus.EDITED)


@dataclass(frozen=True)
class PendingItem:
    kind: ArtifactKind
    section: str
    index: int
    label: str
    provenance: ProvenanceSource
    validation: ValidationStatus
    confidence: float


@dataclass(frozen=True)
class ValidationDecision:
    kind: ArtifactKind
    index: int
    action: str
    section: str = ""
    patch: dict | None = None


def _coerce(value):
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    if value is None or isinstance(value, str):
        return value
    return str(value)


class ContextValidationService:
    def __init__(self, registry, store, registry_service):
        self._registry = registry
        self._store = store
        self._registry_service = registry_service

    async def list_pending(self, ctx, *, connection_id: str,
                           scope: str = "connection") -> list[PendingItem]:
        active = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        if active is None:
            return []
        items: list[PendingItem] = []
        for kind in active.artifact_kinds:
            artifact = await self._store.get(ctx, active.context_id, kind)
            if artifact is not None:
                items.extend(self._pending_items(kind, artifact))
        return items

    @staticmethod
    def _pending_items(kind: ArtifactKind, artifact) -> list[PendingItem]:
        items: list[PendingItem] = []
        if kind is ArtifactKind.ONTOLOGY and isinstance(artifact, OntologyContext):
            for index, concept in enumerate(artifact.concepts):
                if concept.validation is ValidationStatus.PENDING:
                    items.append(PendingItem(kind, "concepts", index, concept.name,
                                             concept.provenance, concept.validation,
                                             concept.confidence))
            for index, relationship in enumerate(artifact.relationships):
                if relationship.validation is ValidationStatus.PENDING:
                    items.append(PendingItem(
                        kind, "relationships", index,
                        f"{relationship.subject} {relationship.kind} {relationship.object}",
                        relationship.provenance, relationship.validation,
                        relationship.confidence))
        elif kind is ArtifactKind.TAXONOMY and isinstance(artifact, TaxonomyContext):
            for index, node in enumerate(artifact.nodes):
                if node.validation is ValidationStatus.PENDING:
                    items.append(PendingItem(kind, "nodes", index, " / ".join(node.path),
                                             node.provenance, node.validation, node.confidence))
        elif kind is ArtifactKind.GRANULARITY and isinstance(artifact, GranularityContext):
            for index, grain in enumerate(artifact.grains):
                if grain.validation is ValidationStatus.PENDING:
                    items.append(PendingItem(kind, "grains", index, grain.table,
                                             grain.source, grain.validation, grain.confidence))
        return items

    async def apply(self, ctx, *, connection_id: str, scope: str = "connection",
                    decisions: tuple[ValidationDecision, ...] = ()) -> object:
        decisions = tuple(decisions)
        if not decisions:
            raise DatahekError(ErrorCode.VALIDATION, "No validation decisions provided")
        for decision in decisions:
            self._check_decision(decision)
        active = await self._registry.active(ctx, connection_id=connection_id, scope=scope)
        if active is None:
            raise DatahekError(ErrorCode.NOT_FOUND,
                               f"No active context for connection '{connection_id}'")

        artifacts: dict[ArtifactKind, object] = {}
        for kind in active.artifact_kinds:
            artifact = await self._store.get(ctx, active.context_id, kind)
            if artifact is not None:
                artifacts[kind] = artifact
        if ArtifactKind.SCHEMA not in artifacts:
            raise DatahekError(ErrorCode.VALIDATION,
                               "Active context has no schema artifact to validate against")

        for decision in decisions:
            artifacts[decision.kind] = self._apply_decision(artifacts[decision.kind], decision)

        stamp = datetime.now(timezone.utc).isoformat()
        freshness = evaluate_freshness(generated_at=stamp,
                                       artifact_schema_hash=active.schema_hash)
        quality = evaluate_quality(
            schema=artifacts[ArtifactKind.SCHEMA],
            profiles=artifacts.get(ArtifactKind.PROFILE),
            topology=artifacts.get(ArtifactKind.TOPOLOGY),
            granularity=artifacts.get(ArtifactKind.GRANULARITY),
            taxonomy=artifacts.get(ArtifactKind.TAXONOMY),
            ontology=artifacts.get(ArtifactKind.ONTOLOGY),
            freshness=freshness)
        return await self._registry_service.publish(
            ctx, connection_id=connection_id, scope=scope,
            schema_hash=active.schema_hash, artifacts=artifacts, quality=quality,
            freshness=freshness, notes="human validation")

    @staticmethod
    def _check_decision(decision: ValidationDecision) -> None:
        if decision.action not in _ACTIONS:
            raise DatahekError(ErrorCode.VALIDATION,
                               f"Unknown validation action '{decision.action}'",
                               details={"allowed": list(_ACTIONS)})
        sections = _SECTIONS.get(decision.kind)
        if sections is None:
            raise DatahekError(ErrorCode.VALIDATION,
                               f"Artifact '{decision.kind.value}' is not reviewable")
        section = decision.section or sections[0]
        if section not in sections:
            raise DatahekError(ErrorCode.VALIDATION,
                               f"Unknown section '{section}' for '{decision.kind.value}'",
                               details={"allowed": list(sections)})
        if decision.action == "edit":
            if not decision.patch:
                raise DatahekError(ErrorCode.VALIDATION, "edit requires a patch")
            allowed = _EDITABLE[decision.kind][section]
            unknown = sorted(set(decision.patch) - allowed)
            if unknown:
                raise DatahekError(ErrorCode.VALIDATION,
                                   f"Fields are not editable: {unknown}",
                                   details={"editable": sorted(allowed)})

    @staticmethod
    def _apply_decision(artifact, decision: ValidationDecision):
        section = decision.section or _SECTIONS[decision.kind][0]
        values = list(getattr(artifact, section))
        if decision.index < 0 or decision.index >= len(values):
            raise DatahekError(
                ErrorCode.VALIDATION,
                f"Item index {decision.index} out of range for '{section}'",
                details={"size": len(values)})
        item = values[decision.index]
        provenance_field = _PROVENANCE_FIELD.get(decision.kind, "provenance")
        if decision.action == "approve":
            item = replace(item, validation=ValidationStatus.APPROVED,
                           **{provenance_field: ProvenanceSource.HUMAN_VALIDATED})
        elif decision.action == "edit":
            patch = {key: _coerce(value) for key, value in (decision.patch or {}).items()}
            item = replace(item, **patch, validation=ValidationStatus.EDITED,
                           **{provenance_field: ProvenanceSource.HUMAN_VALIDATED})
        else:
            item = replace(item, validation=ValidationStatus.REJECTED)
        values[decision.index] = item
        return replace(artifact, **{section: tuple(values)})
