"""Integration tests for the stdio MCP server and its Codex subprocess."""

import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "codex-usage.py"
FAKE_CODEX = '''#!/usr/bin/env python3
import json
import os
import sys
import time

assert sys.argv[1:] == ["app-server"]
mode = os.environ.get("FAKE_CODEX_MODE", "success")
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        print(json.dumps({"method": "account/updated", "params": {}}), flush=True)
        print(json.dumps({"id": request["id"], "result": {}}), flush=True)
    elif method == "account/rateLimits/read":
        if mode == "error":
            print(json.dumps({"id": request["id"], "error": {"code": -32000, "message": "not authenticated"}}), flush=True)
        elif mode == "hang":
            time.sleep(60)
        else:
            print(json.dumps({"id": request["id"], "result": {"rateLimits": {"primary": {"usedPercent": 12, "windowDurationMins": 300}}}}), flush=True)
'''


def request(request_id, method, params=None):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


class McpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.fake_codex = Path(self.tempdir.name) / "codex"
        self.fake_codex.write_text(FAKE_CODEX, encoding="utf-8")
        self.fake_codex.chmod(0o755)
        self.env = dict(os.environ, CODEX_CLI=str(self.fake_codex))

    def exchange(self, messages, env=None):
        run = subprocess.run(
            [sys.executable, str(SERVER)],
            input="".join(json.dumps(message) + "\n" for message in messages),
            text=True, capture_output=True, env=env or self.env,
            timeout=10, check=True,
        )
        return [json.loads(line) for line in run.stdout.splitlines()]

    def test_handshake_discovery_and_multiple_calls(self):
        messages = [
            request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request(2, "tools/list"),
            request(3, "tools/call", {"name": "get_codex_usage", "arguments": {}}),
            request(4, "tools/call", {"name": "get_codex_usage", "arguments": {}}),
        ]
        replies = self.exchange(messages)
        self.assertEqual([reply["id"] for reply in replies], [1, 2, 3, 4])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[1]["result"]["tools"][0]["name"], "get_codex_usage")
        for reply in replies[2:]:
            self.assertNotIn("isError", reply["result"])
            usage = json.loads(reply["result"]["content"][0]["text"])
            self.assertEqual(usage["rateLimits"]["primary"]["usedPercent"], 12)
            self.assertEqual(usage["rateLimits"]["primary"]["windowDurationMins"], 300)

    def test_app_server_error_is_reported_as_tool_error(self):
        env = dict(self.env, FAKE_CODEX_MODE="error")
        reply = self.exchange([request(1, "tools/call", {"name": "get_codex_usage"})], env)[0]
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("not authenticated", reply["result"]["content"][0]["text"])

    def test_missing_executable_is_reported_as_tool_error(self):
        env = dict(self.env, CODEX_CLI=str(Path(self.tempdir.name) / "missing"))
        reply = self.exchange([request(1, "tools/call", {"name": "get_codex_usage"})], env)[0]
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("Could not start Codex CLI", reply["result"]["content"][0]["text"])

    def test_timeout_terminates_app_server(self):
        spec = importlib.util.spec_from_file_location("codex_usage_test", SERVER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_popen = subprocess.Popen
        started = []

        def start(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        # Force the response queue to time out immediately so this test does not
        # need to wait for the production timeout. The child must still be reaped.
        with mock.patch.dict(os.environ, self.env), \
             mock.patch.object(module.subprocess, "Popen", side_effect=start), \
             mock.patch.object(module.queue, "Queue") as response_queue:
            response_queue.return_value.get.side_effect = queue.Empty
            with self.assertRaisesRegex(RuntimeError, "Timed out during app-server initialization"):
                module.read_usage()
        self.assertEqual(len(started), 1)
        self.assertIsNotNone(started[0].poll())
        self.assertTrue(started[0].stdin.closed)
        self.assertTrue(started[0].stdout.closed)


if __name__ == "__main__":
    unittest.main()
