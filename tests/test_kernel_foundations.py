"""Kernel foundations: config, ids, request context, errors, events."""
import os
import unittest

from datahek.kernel import ids
from datahek.kernel.config import Config, config_from_env, dump_safe
from datahek.kernel.context import RequestContext, TenantScope
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.kernel.events import DomainEvent, EventStore


class TestConfig(unittest.TestCase):
    def test_defaults_and_env_merge(self):
        class AppConfig(Config):
            debug: bool = False
            max_rows: int = 1000
            server_host: str = "localhost"

        os.environ["DH_DEBUG"] = "true"
        os.environ["DH_MAX_ROWS"] = "500"
        os.environ["DH_SERVER_HOST"] = "0.0.0.0"
        try:
            cfg = config_from_env(AppConfig, prefix="DH_")
            self.assertTrue(cfg.debug)
            self.assertEqual(cfg.max_rows, 500)
            self.assertEqual(cfg.server_host, "0.0.0.0")
        finally:
            for k in ("DH_DEBUG", "DH_MAX_ROWS", "DH_SERVER_HOST"):
                os.environ.pop(k, None)

    def test_missing_optional_keeps_default(self):
        class C(Config):
            port: int = 8000

        cfg = config_from_env(C, prefix="DH_NOPE_")
        self.assertEqual(cfg.port, 8000)

    def test_unknown_env_key_is_ignored(self):
        class C(Config):
            a: int = 1

        os.environ["DH_ZZZ_UNKNOWN"] = "123"
        try:
            cfg = config_from_env(C, prefix="DH_")
            self.assertEqual(cfg.a, 1)
        finally:
            os.environ.pop("DH_ZZZ_UNKNOWN", None)

    def test_invalid_value_raises(self):
        class C(Config):
            retries: int = 3

        os.environ["DH_RETRIES"] = "not-a-number"
        try:
            with self.assertRaises(ValueError):
                config_from_env(C, prefix="DH_")
        finally:
            os.environ.pop("DH_RETRIES", None)

    def test_dump_safe_never_contains_secrets(self):
        class C(Config):
            password: str = "hunter2"
            host: str = "db"

        dumped = dump_safe(C(password="hunter2"))
        self.assertNotIn("hunter2", str(dumped))


class TestIds(unittest.TestCase):
    def test_id_uniqueness(self):
        self.assertNotEqual(ids.new_id(), ids.new_id())

    def test_id_is_sortable_by_time(self):
        a = ids.new_id()
        b = ids.new_id()
        self.assertLess(a, b)

    def test_id_format(self):
        self.assertEqual(len(ids.new_id()), 40)
        self.assertTrue(ids.new_id().isalnum())

    def test_entity_id(self):
        eid = ids.entity_id("connection")
        self.assertTrue(eid.startswith("conn_"))
        self.assertEqual(len(eid), 40 + 5)


class TestRequestContext(unittest.TestCase):
    def test_default_context(self):
        ctx = RequestContext(source="cli")
        self.assertEqual(ctx.organization_id, "default")
        self.assertEqual(ctx.project_id, "default")
        self.assertEqual(ctx.user_id, "anonymous")
        self.assertFalse(ctx.authenticated)

    def test_full_context(self):
        ctx = RequestContext(
            user_id="alice",
            organization_id="org-1",
            project_id="proj-1",
            roles=frozenset({"analyst"}),
            permissions=frozenset({"connection.read"}),
            source="api",
            authenticated=True,
        )
        self.assertEqual(ctx.roles, frozenset({"analyst"}))
        self.assertIn("connection.read", ctx.permissions)
        self.assertTrue(ctx.authenticated)

    def test_tenant_scope(self):
        scope = TenantScope(organization_id="o1", workspace_id=None, project_id="p1", resolved_by="header")
        self.assertEqual(scope.project_id, "p1")
        self.assertEqual(scope.resolved_by, "header")


class TestErrors(unittest.TestCase):
    def test_error_code_set(self):
        codes = {c.value for c in ErrorCode}
        for expected in ("NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "QUERY_DENIED",
                         "QUERY_TIMEOUT", "RATE_LIMITED", "CONNECTION_FAILED",
                         "PLAN_INVALID", "INTERNAL"):
            self.assertIn(expected, codes)

    def test_error_payload(self):
        err = DatahekError(ErrorCode.NOT_FOUND, "Connection not found", details={"id": "c1"})
        payload = err.to_dict()
        self.assertEqual(payload["code"], "NOT_FOUND")
        self.assertEqual(payload["message"], "Connection not found")
        self.assertEqual(payload["details"], {"id": "c1"})

    def test_error_is_exception(self):
        with self.assertRaises(DatahekError):
            raise DatahekError(ErrorCode.FORBIDDEN, "nope")


class TestEvents(unittest.TestCase):
    def test_event_roundtrip(self):
        ev = DomainEvent(type="connection.created", actor="alice", payload={"id": "c1"}, tenant={"org": "o1"})
        data = ev.to_dict()
        restored = DomainEvent.from_dict(data)
        self.assertEqual(restored.type, "connection.created")
        self.assertEqual(restored.actor, "alice")
        self.assertEqual(restored.tenant, {"org": "o1"})
        self.assertEqual(restored.event_id, ev.event_id)

    def test_event_store_append(self):
        store = EventStore()
        store.record(DomainEvent(type="a", actor="x"))
        store.record(DomainEvent(type="b", actor="x"))
        self.assertEqual(len(store.events()), 2)
        self.assertEqual(store.events()[0].type, "a")


if __name__ == "__main__":
    unittest.main()