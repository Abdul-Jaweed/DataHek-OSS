"""build_default_container — the OSS service composition.

Enterprise replaces implementations via ``Container.override`` — the agent
and API code never change.
"""
from datahek.contracts.audit import AuditSink
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.evaluation import EvaluationStore
from datahek.contracts.misc import ConversationStore
from datahek.contracts.models import ModelProvider
from datahek.contracts.policy import PolicyEngine
from datahek.contracts.prompts import PromptStore
from datahek.contracts.reasoner import Reasoner
from datahek.contracts.secrets import SecretsProvider
from datahek.contracts.tenancy import TenantContext
from datahek.connectors.clickhouse import ClickHouseProvider
from datahek.connectors.mysql import MySQLProvider
from datahek.connectors.postgres import PostgresProvider
from datahek.connectors.sqlite import SQLiteProvider
from datahek.defaults.audit import JsonlAuditSink
from datahek.defaults.auth import AuthConfig, LocalAuthProvider
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.conversations import SqliteConversationStore
from datahek.defaults.evaluation import InMemoryEvaluationStore, LocalEvaluator
from datahek.defaults.masking import TagBasedMaskingPolicy
from datahek.defaults.models import OpenAICompatibleModelProvider
from datahek.defaults.policy import LocalPolicyEngine
from datahek.defaults.prompts import SqlitePromptStore
from datahek.defaults.secrets import EnvSecretsProvider
from datahek.defaults.tenancy import SingleTenantContext
from datahek.engine.executor import Engine, ProviderRegistry
from datahek.engine.planner import Planner
from datahek.engine.reasoner import ModelReasoner
from datahek.engine.schema import SchemaService
from datahek.kernel.config import config_from_env
from datahek.kernel.di import Container
from datahek.kernel.entitlements import EntitlementProvider


def build_default_container() -> Container:
    c = Container()
    c.register(AuthConfig, config_from_env(AuthConfig, prefix="DATAHEK_AUTH_"), singleton=True)
    c.register(AuthProvider, LocalAuthProvider.from_env(), singleton=True)
    c.register(TenantContext, SingleTenantContext(), singleton=True)
    c.register(AuditSink, JsonlAuditSink(), singleton=True)
    c.register(PolicyEngine, LocalPolicyEngine(), singleton=True)
    c.register(SecretsProvider, EnvSecretsProvider(), singleton=True)
    c.register(ConnectionManager, LocalConnectionManager(), singleton=True)
    c.register(EntitlementProvider, EntitlementProvider(), singleton=True)
    c.register(ConversationStore, SqliteConversationStore(), singleton=True)
    c.register(PromptStore, SqlitePromptStore(), singleton=True)
    return c


def build_app_container() -> Container:
    """OSS composition for the API surface: engine + planner + schema + model."""
    c = build_default_container()

    registry = ProviderRegistry()
    registry.register(ClickHouseProvider())
    registry.register(PostgresProvider())
    registry.register(MySQLProvider())
    registry.register(SQLiteProvider())
    c.register(ProviderRegistry, registry, singleton=True)
    c.register(SchemaService, SchemaService(), singleton=True)
    c.register(ModelProvider, OpenAICompatibleModelProvider(), singleton=True)
    c.register(EvaluationStore, InMemoryEvaluationStore(), singleton=True)

    c.register(Planner, lambda: Planner(
        model=c.resolve(ModelProvider),
        schema_service=c.resolve(SchemaService),
    ), singleton=True)
    c.register(Reasoner, lambda: ModelReasoner(model=c.resolve(ModelProvider)), singleton=True)
    c.register(Engine, lambda: Engine(
        registry=c.resolve(ProviderRegistry),
        schema_service=c.resolve(SchemaService),
        audit_sink=c.resolve(AuditSink),
        evaluation_hook=LocalEvaluator(c.resolve(EvaluationStore)),
        masking_policy=TagBasedMaskingPolicy(),
    ), singleton=True)
    return c