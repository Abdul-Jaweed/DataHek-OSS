"""Contracts are structural Protocols; OSS default implementations satisfy them."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from datahek.contracts.audit import AuditEvent, AuditSink
from datahek.contracts.auth import AuthProvider, AuthenticatedIdentity
from datahek.contracts.connections import ConnectionManager
from datahek.contracts.guardrails import Guardrail, GuardrailDecision, GuardrailResult
from datahek.contracts.policy import PolicyDecision, PolicyEngine
from datahek.contracts.providers import DataProvider, ReadOnlyLevel
from datahek.contracts.secrets import SecretRef, SecretsProvider
from datahek.contracts.tenancy import TenantContext
from datahek.defaults.audit import JsonlAuditSink
from datahek.defaults.auth import LocalAuthProvider
from datahek.defaults.container import build_default_container
from datahek.defaults.policy import LocalPolicyEngine
from datahek.defaults.secrets import EnvSecretsProvider
from datahek.defaults.tenancy import SingleTenantContext
from datahek.kernel.context import RequestContext


class TestContractShapes(unittest.TestCase):
    """Structural conformance: defaults satisfy their protocols."""

    def test_auth_default_conforms(self):
        self.assertIsInstance(LocalAuthProvider(), AuthProvider)
        self.assertTrue(issubclass(LocalAuthProvider, AuthProvider))

    def test_tenant_default_conforms(self):
        self.assertTrue(issubclass(SingleTenantContext, TenantContext))

    def test_audit_default_conforms(self):
        self.assertTrue(issubclass(JsonlAuditSink, AuditSink))

    def test_policy_default_conforms(self):
        self.assertTrue(issubclass(LocalPolicyEngine, PolicyEngine))

    def test_secrets_default_conforms(self):
        self.assertTrue(issubclass(EnvSecretsProvider, SecretsProvider))

    def test_decision_values(self):
        for v in ("ALLOW", "DENY", "REDACT", "MASK", "REQUIRE_APPROVAL", "RATE_LIMIT"):
            self.assertIn(v, GuardrailDecision.__args__)

    def test_read_only_levels(self):
        self.assertEqual(ReadOnlyLevel.STRUCTURAL.value, "structural")


class TestAuthDefault(unittest.TestCase):
    def test_authenticate_known_user(self):
        provider = LocalAuthProvider(users={"alice": "pw"})
        ident = asyncio.run(provider.authenticate("alice", "pw"))
        self.assertEqual(ident.user_id, "alice")
        self.assertTrue(ident.authenticated)

    def test_authenticate_wrong_password(self):
        provider = LocalAuthProvider(users={"alice": "pw"})
        ident = asyncio.run(provider.authenticate("alice", "nope"))
        self.assertFalse(ident.authenticated)

    def test_unknown_user(self):
        provider = LocalAuthProvider(users={"alice": "pw"})
        ident = asyncio.run(provider.authenticate("bob", "pw"))
        self.assertFalse(ident.authenticated)


class TestTenantDefault(unittest.TestCase):
    def test_single_tenant_resolves_default(self):
        ctx = RequestContext(source="api")
        tenant = asyncio.run(SingleTenantContext().resolve(ctx))
        self.assertEqual(tenant.organization_id, "default")
        self.assertEqual(tenant.project_id, "default")
        self.assertEqual(tenant.resolved_by, "default")


class TestPolicyDefault(unittest.TestCase):
    def test_allowlist_allows(self):
        engine = LocalPolicyEngine(allowed_tables={"logs", "traces"})
        decision = asyncio.run(engine.evaluate({"table": "logs"}))
        self.assertEqual(decision["action"], "ALLOW")

    def test_allowlist_denies(self):
        engine = LocalPolicyEngine(allowed_tables={"logs"})
        decision = asyncio.run(engine.evaluate({"table": "finance"}))
        self.assertEqual(decision["action"], "DENY")
        self.assertIn("finance", decision["reason"])

    def test_large_limit_on_raw_rows_requires_approval(self):
        from datahek.engine.plan import LogicalPlan, ReadNode

        engine = LocalPolicyEngine(approval_row_limit=1000)
        plan = LogicalPlan(nodes=[ReadNode(source="events", columns=["service"], limit=5000)])
        decision = asyncio.run(engine.evaluate({"plan": plan}))
        self.assertEqual(decision["action"], "REQUIRE_APPROVAL")

    def test_aggregate_plan_ignores_row_limit(self):
        from datahek.engine.plan import Aggregate, LogicalPlan, ReadNode

        engine = LocalPolicyEngine(approval_row_limit=1000)
        plan = LogicalPlan(nodes=[ReadNode(
            source="events", columns=["service"], group_by=["service"],
            aggregates=[Aggregate(function="count", column="*", alias="n")],
            limit=1_000_000)])
        decision = asyncio.run(engine.evaluate({"plan": plan}))
        self.assertEqual(decision["action"], "ALLOW")


class TestAuditDefault(unittest.TestCase):
    def test_jsonl_write(self):
        with tempfile.TemporaryDirectory() as d:
            sink = JsonlAuditSink(Path(d) / "audit.jsonl")
            ev = AuditEvent(event_type="connection.created", actor="alice",
                            action="create", resource_ref="conn_1", tenant={"org": "o1"})
            asyncio.run(sink.record(ev))
            lines = (Path(d) / "audit.jsonl").read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            data = json.loads(lines[0])
            self.assertEqual(data["event_type"], "connection.created")
            self.assertEqual(data["actor"], "alice")


class TestSecretsDefault(unittest.TestCase):
    def test_env_secret_resolution(self):
        import os
        os.environ["DH_TEST_SECRET"] = "s3cret"
        try:
            provider = EnvSecretsProvider(prefix="DH_")
            value = asyncio.run(provider.get_secret(SecretRef(provider="env", name="TEST_SECRET")))
            self.assertEqual(value.value, "s3cret")
        finally:
            os.environ.pop("DH_TEST_SECRET", None)

    def test_missing_secret_raises(self):
        provider = EnvSecretsProvider(prefix="DH_MISSING_")
        with self.assertRaises(KeyError):
            asyncio.run(provider.get_secret(SecretRef(provider="env", name="NOPE")))


class TestContainer(unittest.TestCase):
    def test_default_container_wires_oss_defaults(self):
        c = build_default_container()
        self.assertTrue(c.has(AuthProvider))
        self.assertTrue(c.has(TenantContext))
        self.assertTrue(c.has(AuditSink))
        self.assertTrue(c.has(PolicyEngine))
        self.assertTrue(c.has(SecretsProvider))
        self.assertTrue(c.has(ConnectionManager))

    def test_default_container_resolves(self):
        c = build_default_container()
        auth = c.resolve(AuthProvider)
        self.assertIsInstance(auth, LocalAuthProvider)
        tenant = c.resolve(TenantContext)
        self.assertIsInstance(tenant, SingleTenantContext)


class TestGuardrailContract(unittest.TestCase):
    def test_result_shape(self):
        r = GuardrailResult(decision="ALLOW", reason="ok")
        self.assertEqual(r.decision, "ALLOW")


if __name__ == "__main__":
    unittest.main()