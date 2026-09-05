"""Kernel services: DI container, capability model, extension registry, entitlements."""
import unittest

from datahek.kernel.capabilities import Capabilities
from datahek.kernel.di import Container, NotResolvable
from datahek.kernel.entitlements import EntitlementProvider, ResourceLimits
from datahek.kernel.registry import ExtensionRegistry, AlreadyRegistered


class _A:
    def ping(self):
        return "a"


class _B:
    def __init__(self, a: _A):
        self.a = a


class TestContainer(unittest.TestCase):
    def test_resolve_instance(self):
        c = Container()
        c.register(_A, _A())
        self.assertEqual(c.resolve(_A).ping(), "a")

    def test_resolve_factory(self):
        c = Container()
        c.register(_A, lambda: _A())
        self.assertEqual(c.resolve(_A).ping(), "a")

    def test_resolve_singleton(self):
        c = Container()
        c.register(_A, _A(), singleton=True)
        self.assertIs(c.resolve(_A), c.resolve(_A))

    def test_resolve_not_registered_raises(self):
        c = Container()
        with self.assertRaises(NotResolvable):
            c.resolve(_B)

    def test_override(self):
        class _A2(_A):
            pass

        c = Container()
        c.register(_A, _A())
        c.override(_A, _A2())
        self.assertIsInstance(c.resolve(_A), _A2)

    def test_has(self):
        c = Container()
        c.register(_A, _A())
        self.assertTrue(c.has(_A))
        self.assertFalse(c.has(_B))


class TestCapabilities(unittest.TestCase):
    def test_supports(self):
        caps = Capabilities(sso=False, multi_tenancy=False, policy_engine=False,
                            centralized_audit=False, usage_analytics=False,
                            high_availability=False, advanced_rbac=False)
        self.assertFalse(caps.supports("sso"))
        self.assertFalse(caps.supports("multi_tenancy"))

    def test_supports_unknown_is_false(self):
        caps = Capabilities()
        self.assertFalse(caps.supports("magic"))

    def test_enterprise_profile(self):
        caps = Capabilities(sso=True, multi_tenancy=True, policy_engine=True,
                            centralized_audit=True, usage_analytics=True,
                            high_availability=True, advanced_rbac=True)
        for name in ("sso", "multi_tenancy", "policy_engine", "advanced_rbac",
                     "centralized_audit", "usage_analytics", "high_availability"):
            self.assertTrue(caps.supports(name))


class TestExtensionRegistry(unittest.TestCase):
    def test_register_and_get(self):
        r = ExtensionRegistry()
        r.register("auth", _A())
        self.assertIsInstance(r.get("auth"), _A)

    def test_duplicate_registration_raises(self):
        r = ExtensionRegistry()
        r.register("a", _A())
        with self.assertRaises(AlreadyRegistered):
            r.register("a", _A())

    def test_names(self):
        r = ExtensionRegistry()
        r.register("x", _A())
        self.assertEqual(r.names(), ["x"])


class TestEntitlements(unittest.TestCase):
    def test_static_defaults(self):
        p = EntitlementProvider()
        self.assertTrue(p.check("mcp.servers", 3))
        self.assertFalse(p.check("mcp.servers", 4))
        self.assertTrue(p.check("prompt.templates", 3))
        self.assertFalse(p.check("prompt.templates", 4))
        self.assertTrue(p.check("connections", 5))
        self.assertTrue(p.check("projects", 1))

    def test_resource_limits(self):
        limits = ResourceLimits(mcp_servers=3, prompt_templates=3, connections=5,
                                projects=1, users=5, evaluation_datasets=3)
        self.assertEqual(limits.mcp_servers, 3)

    def test_unknown_resource_allowed(self):
        p = EntitlementProvider()
        self.assertTrue(p.check("anything.else", 100))


if __name__ == "__main__":
    unittest.main()