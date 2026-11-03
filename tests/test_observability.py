import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import http.client
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "skill" / "scripts" / "gf_observe.py"
SPEC = importlib.util.spec_from_file_location("gf_observe", MODULE)
observe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observe)
CONF_SPEC = importlib.util.spec_from_file_location("configure_hooks", ROOT / "configure_hooks.py")
config = importlib.util.module_from_spec(CONF_SPEC)
CONF_SPEC.loader.exec_module(config)


class ObserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rid = observe.new_run(self.root, "A sample greenfield product")

    def test_real_hook_agent_lifecycle(self):
        for event in ("SubagentStart", "PreToolUse", "SubagentStop"):
            observe.hook_event(self.root, "claude", {"hook_event_name": event, "agent_id": "agent-10", "agent_type": "gf-market", "session_id": "abc", "tool_name": "WebSearch", "tool_input": {"password": "secret-value"}})
        result = observe.current_state(self.root, self.rid)
        market = next(a for a in result["agents"] if a["name"] == "gf-market")
        self.assertEqual(market["status"], "completed")
        self.assertEqual(market["tools"], 1)
        self.assertEqual(result["stats"]["started_agents"], 1)
        self.assertNotIn("secret-value", json.dumps(result))

    def test_unrelated_hooks_ignored(self):
        observe.hook_event(self.root, "claude", {"hook_event_name": "SubagentStart", "agent_type": "general-purpose", "agent_id": "other"})
        self.assertEqual(len(observe.parse_events(self.root, self.rid)), 1)

    def test_codex_specialist_normalization(self):
        observe.hook_event(self.root, "codex", {"hook_event_name": "SubagentStart", "agent_type": "gf_economics", "agent_id": "codex-agent"})
        state = observe.current_state(self.root, self.rid)
        self.assertEqual(next(a for a in state["agents"] if a["name"] == "gf-economics")["status"], "running")

    def test_codex_json_stream_sanitized(self):
        lines = "\n".join([
            '{"type":"thread.started","thread_id":"thread1"}',
            '{"type":"item.started","item":{"id":"1","type":"command_execution","command":"print(SECRET_TOKEN_1)"}}',
            '{"type":"item.completed","item":{"id":"1","type":"command_execution","output":"SECRET_TOKEN_2"}}',
            '{"type":"item.completed","item":{"type":"reasoning","text":"hidden thought"}}',
            '{"type":"turn.completed","usage":{"input_tokens":120,"output_tokens":30}}',
        ])
        self.assertEqual(observe.ingest_codex(self.root, self.rid, io.StringIO(lines)), 4)
        state = observe.current_state(self.root, self.rid)
        serialized = json.dumps(state)
        self.assertEqual(state["stats"]["reported_tokens"], 150)
        self.assertEqual(state["stats"]["tool_calls"], 1)
        self.assertNotIn("SECRET_TOKEN", serialized)
        self.assertNotIn("hidden thought", serialized)

    def test_url_security(self):
        self.assertEqual(observe.safe_url("http://localhost/private"), "")
        self.assertEqual(observe.safe_url("http://127.0.0.1/secret"), "")
        self.assertEqual(observe.safe_url("https://someone:password@public.example/"), "")
        self.assertEqual(observe.safe_url("file:///etc/passwd"), "")
        self.assertEqual(observe.safe_url("https://www.census.gov/data?api_key=ABC#part"), "https://www.census.gov/data")

    def test_no_false_completion_for_quiet_agents(self):
        observe.emit(self.root, self.rid, "agent_started", agent="gf-problem")
        state = observe.current_state(self.root, self.rid)
        self.assertEqual(state["stats"]["finished_agents"], 0)
        self.assertEqual(state["status"], "running")

    def test_empty_run_explicit_not_started(self):
        state = observe.current_state(self.root, self.rid)
        self.assertEqual(state["stats"]["started_agents"], 0)
        self.assertTrue(all(a["status"] == "queued" for a in state["agents"]))
        self.assertEqual(state["meta"]["demo"], False)

    def test_local_http_server_read_only(self):
        from pathlib import Path
        server = ThreadingHTTPServer(("127.0.0.1", 0), observe.Handler)
        server.project = self.root
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            root = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(root + "/api/state?run=" + self.rid, timeout=2) as resp:
                state = json.load(resp)
                self.assertEqual(state["meta"]["run_id"], self.rid)
            with urllib.request.urlopen(root, timeout=2) as resp:
                html = resp.read().decode()
                self.assertIn("Agent Mission Control", html)
                self.assertIn("No agents have started", html)
                self.assertIn("<html", html)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def _serve(self, allow=()):
        server = ThreadingHTTPServer(("127.0.0.1", 0), observe.Handler)
        server.project, server.allow_hosts = self.root, list(allow)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(timeout=3)
        self.addCleanup(stop)
        return server.server_port

    def _get(self, port, path, **headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        c.putrequest("GET", path, skip_host=True)
        for k, v in headers.items():
            c.putheader(k.replace("_", "-"), v)
        c.endheaders()
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_foreign_host_rejected(self):
        port = self._serve()
        for path in ("/", "/api/runs", "/api/state?run=" + self.rid):
            for host in (f"evil.example:{port}", f"localhost.:{port}", None):
                status, body = self._get(port, path, **({"Host": host} if host else {}))
                self.assertEqual(status, 421, (path, host))
                self.assertNotIn("sample greenfield", body)

    def test_cross_origin_api_rejected(self):
        port = self._serve()
        self.assertEqual(self._get(port, "/api/runs", Host=f"127.0.0.1:{port}", Origin="https://evil.example")[0], 403)
        self.assertEqual(self._get(port, "/api/runs", Host=f"127.0.0.1:{port}", Origin="chrome-extension://abc")[0], 403)

    def test_sec_fetch_cross_site_rejected(self):
        port = self._serve()
        for site in ("cross-site", "same-site"):
            self.assertEqual(self._get(port, "/api/runs", Host=f"127.0.0.1:{port}", Sec_Fetch_Site=site)[0], 403)

    def test_localhost_and_loopback_allowed(self):
        port = self._serve()
        for host in (f"127.0.0.1:{port}", f"LocalHost:{port}"):
            self.assertEqual(self._get(port, "/", Host=host)[0], 200)
            ok = dict(Host=host, Origin=f"http://{host}", Sec_Fetch_Site="same-origin")
            self.assertEqual(self._get(port, "/api/runs", **ok)[0], 200)
        self.assertEqual(self._get(port, "/api/runs", Host=f"127.0.0.1:{port}", Sec_Fetch_Site="none")[0], 200)

    def test_allow_host_flag(self):
        port = self._serve(allow=["devbox.internal"])
        self.assertEqual(self._get(port, "/api/runs", Host=f"devbox.internal:{port}")[0], 200)
        self.assertEqual(self._get(port, "/api/runs", Host=f"other.internal:{port}")[0], 421)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            observe.file_paths(self.root, "../../foo")


class HookInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = subprocess.run([sys.executable, str(ROOT / "install.py"), "--project", str(self.root)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def invoke(self, mode):
        return subprocess.run([sys.executable, str(ROOT / "configure_hooks.py"), mode, "--project", str(self.root)], capture_output=True, text=True)

    def test_enable_preserve_idempotent_remove(self):
        path = self.root / ".claude/settings.local.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        unrelated = {"custom": {"retain": True}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo unrelated"}]}]}}
        path.write_text(json.dumps(unrelated))
        for _ in range(2):
            self.assertEqual(self.invoke("install").returncode, 0)
        result = json.loads(path.read_text())
        self.assertEqual(result["custom"], unrelated["custom"])
        self.assertEqual(result["hooks"]["Stop"], unrelated["hooks"]["Stop"])
        self.assertEqual(len(result["hooks"]["SubagentStart"]), 1)
        self.assertEqual(len(result["hooks"]["PreToolUse"]), 1)
        cp = self.root / ".codex/hooks.json"
        self.assertIn("SubagentStart", json.loads(cp.read_text())["hooks"])
        self.assertEqual(self.invoke("remove").returncode, 0)
        cleaned = json.loads(path.read_text())
        self.assertEqual(cleaned, unrelated)
        self.assertEqual(json.loads(cp.read_text()), {})

    def _events(self, rel):
        return set(json.loads((self.root / rel).read_text())["hooks"])

    def test_claude_hooks_in_path_containing_codex(self):
        proj = self.root / "codex-work" / "app"
        (proj / ".claude/skills").mkdir(parents=True)
        (proj / ".claude/skills/greenfield-business-evaluator").symlink_to(self.root / ".claude/skills/greenfield-business-evaluator")
        script = proj / ".claude/skills/greenfield-business-evaluator/scripts/gf_observe.py"
        self.assertTrue(script.is_file())
        p = subprocess.run([sys.executable, str(ROOT / "configure_hooks.py"), "install", "--platform", "claude", "--project", str(proj)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(set(json.loads((proj / ".claude/settings.local.json").read_text())["hooks"]), {"SubagentStart", "SubagentStop", "PreToolUse", "PostToolUseFailure"})

    def test_codex_hooks_event_set(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        self.assertEqual(self._events(".codex/hooks.json"), {"SubagentStart", "SubagentStop", "PreToolUse"})
        self.assertEqual(self._events(".claude/settings.local.json"), {"SubagentStart", "SubagentStop", "PreToolUse", "PostToolUseFailure"})

    def test_no_posttooluse_installed(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        for rel in (".claude/settings.local.json", ".codex/hooks.json"):
            self.assertNotIn("PostToolUse", (self.root / rel).read_text().replace("PostToolUseFailure", ""))

    def test_remove_strips_legacy_posttooluse(self):
        cmd = "python3 /x/gf_observe.py hook --project /p --provider claude"
        mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
        legacy = {"PostToolUse": [{"hooks": [{"type": "command", "command": cmd}]}, mine], "PostToolUseFailure": [{"hooks": [{"type": "command", "command": cmd}]}]}
        for rel in (".claude/settings.local.json", ".codex/hooks.json"):
            (self.root / rel).parent.mkdir(exist_ok=True)
            (self.root / rel).write_text(json.dumps({"hooks": legacy}))
        self.assertEqual(self.invoke("remove").returncode, 0)
        for rel in (".claude/settings.local.json", ".codex/hooks.json"):
            self.assertEqual(json.loads((self.root / rel).read_text()), {"hooks": {"PostToolUse": [mine]}})

    def test_transform_requires_platform(self):
        with self.assertRaises(TypeError):
            config.transform(self.root / "x.json", "cmd", "install")
        with self.assertRaises(ValueError):
            config.transform(self.root / "x.json", "cmd", "install", platform="gemini")

    def test_hook_installer_rejects_bad_json(self):
        path = self.root / ".codex/hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid json")
        proc = self.invoke("install")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse((self.root / ".claude/settings.local.json").exists())


if __name__ == "__main__":
    unittest.main()
