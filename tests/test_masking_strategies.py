"""Masking strategies (redact / hash / partial) and MCP tool timeouts."""
import asyncio
import os
import unittest

from datahek.engine.executor import ExecutionInfo, QueryResult


def _result(rows):
    return QueryResult(columns=[{"name": "email", "type": "String"},
                                {"name": "note", "type": "String"}],
                       rows=rows, row_count=len(rows),
                       execution=ExecutionInfo(provider_id="sqlite"))


class TestMaskingStrategies(unittest.TestCase):
    def _masked(self, mode, value="jane@acme.com"):
        from datahek.engine.masking import mask_result
        os.environ["DATAHEK_MASK_MODE"] = mode
        try:
            out = mask_result(_result([(value, "keep")]), {"email"})
        finally:
            os.environ.pop("DATAHEK_MASK_MODE", None)
        return out.rows[0]

    def test_redact_default(self):
        masked, note = self._masked("redact")
        self.assertEqual(masked, "***")
        self.assertEqual(note, "keep")

    def test_hash_is_stable_and_hides_value(self):
        from datahek.engine.masking import mask_result
        os.environ["DATAHEK_MASK_MODE"] = "hash"
        try:
            a = mask_result(_result([("jane@acme.com", "x")]), {"email"}).rows[0][0]
            b = mask_result(_result([("jane@acme.com", "x")]), {"email"}).rows[0][0]
            c = mask_result(_result([("other@acme.com", "x")]), {"email"}).rows[0][0]
        finally:
            os.environ.pop("DATAHEK_MASK_MODE", None)
        self.assertTrue(a.startswith("sha256:"))
        self.assertNotIn("jane", a)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_partial_keeps_last_four(self):
        self.assertEqual(self._masked("partial")[0], "****.com")
        self.assertEqual(self._masked("partial", "4111111111111111")[0], "****1111")

    def test_unknown_mode_falls_back_to_redact(self):
        self.assertEqual(self._masked("nonsense")[0], "***")

    def test_empty_sensitive_set_untouched(self):
        from datahek.engine.masking import mask_result
        out = mask_result(_result([("jane@acme.com", "keep")]), set())
        self.assertEqual(out.rows[0], ("jane@acme.com", "keep"))


class TestMcpToolTimeout(unittest.TestCase):
    def test_timeout_returns_clear_error(self):
        from datahek.mcp_server import run_guarded

        async def slow():
            await asyncio.sleep(5)
            return "late"

        out = asyncio.run(run_guarded(slow(), timeout_s=0.05))
        self.assertIn("timed out", out)

    def test_datahek_error_returned_cleanly(self):
        from datahek.mcp_server import run_guarded
        from datahek.kernel.errors import DatahekError, ErrorCode

        async def failing():
            raise DatahekError(ErrorCode.CONNECTION_NOT_FOUND, "Connection 'x' not found")

        out = asyncio.run(run_guarded(failing(), timeout_s=1))
        self.assertEqual(out, "Error: Connection 'x' not found")

    def test_unexpected_error_is_generic(self):
        from datahek.mcp_server import run_guarded

        async def boom():
            raise RuntimeError("secret detail that must not leak")

        out = asyncio.run(run_guarded(boom(), timeout_s=1))
        self.assertEqual(out, "Error: internal error")
        self.assertNotIn("secret detail", out)

    def test_success_passthrough(self):
        from datahek.mcp_server import run_guarded

        async def ok():
            return "result"

        self.assertEqual(asyncio.run(run_guarded(ok(), timeout_s=1)), "result")


if __name__ == "__main__":
    unittest.main()
