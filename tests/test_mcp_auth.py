"""MCP per-client token auth — opt-in, scope-aware."""
import asyncio
import os
import unittest


class TestMcpAuth(unittest.TestCase):
    def test_disabled_without_env(self):
        from datahek.mcp_server import build_mcp_auth

        os.environ.pop("DATAHEK_MCP_TOKENS", None)
        self.assertIsNone(build_mcp_auth())

    def test_tokens_and_scopes(self):
        from datahek.mcp_server import build_mcp_auth

        os.environ["DATAHEK_MCP_TOKENS"] = "alpha-token, beta-token:read|write"
        try:
            verifier = build_mcp_auth()
            self.assertIsNotNone(verifier)

            async def run():
                ok = await verifier.verify_token("alpha-token")
                self.assertIsNotNone(ok)
                self.assertEqual(ok.client_id, "mcp-alpha-")

                bad = await verifier.verify_token("wrong")
                self.assertIsNone(bad)

                beta = await verifier.verify_token("beta-token")
                self.assertIsNotNone(beta)
                self.assertEqual(set(beta.scopes), {"read", "write"})

            asyncio.run(run())
        finally:
            os.environ.pop("DATAHEK_MCP_TOKENS", None)

    def test_required_scopes_enforced(self):
        from datahek.mcp_server import build_mcp_auth

        os.environ["DATAHEK_MCP_TOKENS"] = "plain-token"
        os.environ["DATAHEK_MCP_REQUIRED_SCOPES"] = "read"
        try:
            verifier = build_mcp_auth()

            async def run():
                denied = await verifier.verify_token("plain-token")
                self.assertIsNone(denied)  # missing required scope

            asyncio.run(run())
        finally:
            os.environ.pop("DATAHEK_MCP_TOKENS", None)
            os.environ.pop("DATAHEK_MCP_REQUIRED_SCOPES", None)

    def test_server_builds_with_auth(self):
        os.environ["DATAHEK_MCP_TOKENS"] = "tok:read"
        try:
            from datahek.mcp_server import build_mcp_server

            server = build_mcp_server()
            self.assertIsNotNone(server)
        finally:
            os.environ.pop("DATAHEK_MCP_TOKENS", None)


if __name__ == "__main__":
    unittest.main()
