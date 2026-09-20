"""build_default_container — the OSS service composition.

Enterprise replaces implementations via ``Container.override`` — the agent
and API code never change.
"""
import os

from datahek.contracts.audit import AuditSink
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.evaluation import EvaluationStore
from datahek.contracts.misc import ConversationStore
from datahek.contracts.models import ModelProvider
from datahek.contracts.policy import PolicyEngine
from datahek.contracts.prompts import PromptStore
from datahek.contracts.saved import SavedQueryStore
from datahek.contracts.semantics import SemanticStore
from datahek.contracts.reasoner import Reasoner
from datahek.contracts.secrets import SecretsProvider
from datahek.contracts.tenancy import TenantContext
from datahek.contracts.verifier import Verifier
from datahek.connectors.clickhouse import ClickHouseProvider
from datahek.connectors.duckdb import DuckDBProvider
from datahek.connectors.mysql import MySQLProvider
from datahek.connectors.postgres import PostgresProvider
from datahek.connectors.sqlite import SQLiteProvider
from datahek.contracts.misc import ApprovalService, CheckpointStore, EntitlementService
from datahek.defaults.approvals_pg import PostgresApprovalService
from datahek.defaults.approvals_sqlite import SqliteApprovalService
from datahek.defaults.checkpoints import SqliteCheckpointStore
from datahek.defaults.checkpoints_pg import PostgresCheckpointStore
from datahek.defaults.audit import JsonlAuditSink
from datahek.defaults.auth import AuthConfig, LocalAuthProvider
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.connections_pg import PostgresConnectionManager
from datahek.defaults.conversations import SqliteConversationStore
from datahek.defaults.conversations_pg import PostgresConversationStore
from datahek.defaults.evaluation import InMemoryEvaluationStore, LocalEvaluator
from datahek.defaults.evaluation_pg import PostgresEvaluationStore
from datahek.defaults.infisical import InfisicalSecretsProvider
from datahek.defaults.masking import TagBasedMaskingPolicy
from datahek.defaults.metrics import LocalMetrics
from datahek.defaults.models import OpenAICompatibleModelProvider
from datahek.defaults.pg import PgMetadata, metadata_config
from datahek.defaults.policy import LocalPolicyEngine
from datahek.defaults.prompts import SqlitePromptStore
from datahek.defaults.prompts_pg import PostgresPromptStore
from datahek.defaults.saved_queries import SqliteSavedQueryStore
from datahek.defaults.semantics import SqliteSemanticStore
from datahek.defaults.semantics_pg import PostgresSemanticStore
from datahek.defaults.redis_llm import RedisLlmSettingsStore
from datahek.defaults.secrets import EnvSecretsProvider
from datahek.defaults.tenancy import SingleTenantContext
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.engine.analyst import MultiStepAnalyst
from datahek.engine.reasoner import ModelReasoner
from datahek.engine.suggestions import FollowUpSuggester
from datahek.engine.verifier import ModelVerifier
from datahek.engine.schema import SchemaService
from datahek.kernel.config import config_from_env
from datahek.kernel.di import Container
from datahek.kernel.entitlements import EntitlementProvider


def build_default_container() -> Container:
    c = Container()
    c.register(AuthConfig, config_from_env(AuthConfig, prefix="DATAHEK_AUTH_"), singleton=True)
    if InfisicalSecretsProvider.is_configured():
        c.register(SecretsProvider, InfisicalSecretsProvider.from_env(), singleton=True)
    else:
        c.register(SecretsProvider, EnvSecretsProvider(), singleton=True)
    if isinstance(c.resolve(SecretsProvider), InfisicalSecretsProvider):
        c.register(AuthProvider,
                   LocalAuthProvider.from_infisical(c.resolve(SecretsProvider)), singleton=True)
    else:
        c.register(AuthProvider, LocalAuthProvider.from_env(), singleton=True)
    c.register(TenantContext, SingleTenantContext(), singleton=True)
    c.register(AuditSink, JsonlAuditSink(), singleton=True)
    c.register(PolicyEngine, LocalPolicyEngine(), singleton=True)
    c.register(ApprovalService, SqliteApprovalService(), singleton=True)
    c.register(CheckpointStore, SqliteCheckpointStore(), singleton=True)
    pg = PgMetadata()
    if pg._url:
        c.register(PgMetadata, pg, singleton=True)
        c.register(ConnectionManager,
                   PostgresConnectionManager(
                       pg, encryption_key=os.environ.get("DATAHEK_ENCRYPTION_KEY")),
                   singleton=True)
        c.register(ConversationStore, PostgresConversationStore(pg), singleton=True)
        c.register(PromptStore, PostgresPromptStore(pg), singleton=True)
        c.register(SemanticStore, PostgresSemanticStore(pg), singleton=True)
        c.register(ApprovalService, PostgresApprovalService(pg), singleton=True)
        c.register(CheckpointStore, PostgresCheckpointStore(pg), singleton=True)
    else:
        c.register(ConnectionManager, LocalConnectionManager(), singleton=True)
        c.register(ConversationStore, SqliteConversationStore(), singleton=True)
        c.register(PromptStore, SqlitePromptStore(), singleton=True)
        c.register(SemanticStore, SqliteSemanticStore(), singleton=True)
    entitlements = EntitlementProvider()
    c.register(EntitlementProvider, entitlements, singleton=True)
    c.register(EntitlementService, entitlements, singleton=True)
    c.register(LocalMetrics, LocalMetrics(), singleton=True)
    c.register(SavedQueryStore, SqliteSavedQueryStore(), singleton=True)
    return c


def build_app_container() -> Container:
    """OSS composition for the API surface: engine + planner + schema + model."""
    c = build_default_container()

    registry = ProviderRegistry()
    registry.register(ClickHouseProvider())
    registry.register(PostgresProvider())
    registry.register(MySQLProvider())
    registry.register(SQLiteProvider())
    registry.register(DuckDBProvider())
    c.register(ProviderRegistry, registry, singleton=True)
    c.register(SchemaService, SchemaService(), singleton=True)

    cfg = metadata_config()
    settings_store = None
    if cfg.redis_url:
        settings_store = RedisLlmSettingsStore(url=cfg.redis_url)
        c.register(RedisLlmSettingsStore, settings_store, singleton=True)

    if isinstance(c.resolve(SecretsProvider), InfisicalSecretsProvider):
        model_provider = OpenAICompatibleModelProvider.from_infisical(c.resolve(SecretsProvider))
        if settings_store is not None and hasattr(model_provider, "_settings_store"):
            model_provider._settings_store = settings_store
    else:
        model_provider = OpenAICompatibleModelProvider(settings_store=settings_store)
    c.register(ModelProvider, model_provider, singleton=True)

    if c.has(PgMetadata) and getattr(c.resolve(PgMetadata), "_url", None):
        c.register(EvaluationStore, PostgresEvaluationStore(c.resolve(PgMetadata)), singleton=True)
    else:
        c.register(EvaluationStore, InMemoryEvaluationStore(), singleton=True)

    c.register(Planner, lambda: Planner(
        model=c.resolve(ModelProvider),
        schema_service=c.resolve(SchemaService),
        secrets=c.resolve(SecretsProvider),
        metrics=c.resolve(SemanticStore),
    ), singleton=True)
    c.register(Reasoner, lambda: ModelReasoner(model=c.resolve(ModelProvider)), singleton=True)
    c.register(Verifier, lambda: ModelVerifier(c.resolve(ModelProvider)), singleton=True)
    c.register(FollowUpSuggester, lambda: FollowUpSuggester(c.resolve(ModelProvider)), singleton=True)
    c.register(MultiStepAnalyst, lambda: MultiStepAnalyst(
        model=c.resolve(ModelProvider),
        planner=c.resolve(Planner),
        engine=c.resolve(Engine),
        reasoner=c.resolve(Reasoner),
    ), singleton=True)
    c.register(Engine, lambda: Engine(
        registry=c.resolve(ProviderRegistry),
        schema_service=c.resolve(SchemaService),
        audit_sink=c.resolve(AuditSink),
        evaluation_hook=LocalEvaluator(c.resolve(EvaluationStore)),
        masking_policy=TagBasedMaskingPolicy(),
        secrets=c.resolve(SecretsProvider),
        policy=c.resolve(PolicyEngine),
        approvals=c.resolve(ApprovalService),
        rate_limit=int(os.environ.get("DATAHEK_RATE_LIMIT_PER_MINUTE", "120")),
    ), singleton=True)
    return c