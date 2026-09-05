"""build_default_container — the OSS service composition.

Enterprise replaces implementations via ``Container.override`` — the agent
and API code never change.
"""
from datahek.contracts.audit import AuditSink
from datahek.contracts.auth import AuthProvider
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.policy import PolicyEngine
from datahek.contracts.secrets import SecretsProvider
from datahek.contracts.tenancy import TenantContext
from datahek.defaults.audit import JsonlAuditSink
from datahek.defaults.auth import LocalAuthProvider
from datahek.defaults.connections import LocalConnectionManager
from datahek.defaults.policy import LocalPolicyEngine
from datahek.defaults.secrets import EnvSecretsProvider
from datahek.defaults.tenancy import SingleTenantContext
from datahek.kernel.di import Container


def build_default_container() -> Container:
    c = Container()
    c.register(AuthProvider, LocalAuthProvider(), singleton=True)
    c.register(TenantContext, SingleTenantContext(), singleton=True)
    c.register(AuditSink, JsonlAuditSink(), singleton=True)
    c.register(PolicyEngine, LocalPolicyEngine(), singleton=True)
    c.register(SecretsProvider, EnvSecretsProvider(), singleton=True)
    c.register(ConnectionManager, LocalConnectionManager(), singleton=True)
    return c