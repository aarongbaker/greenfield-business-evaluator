"""W28 gate: every shell command in the README and docs/ runs as written in a fresh git repo with the network blocked,
and every relative link and anchor resolves.

A line ending in `# needs-agent`, `# needs-network`, `# needs-terminal` (a person typing a code), `# needs-clone` (run from a
checkout of this repo) or `# needs-research` (filled-in research) is not run; its `greenfield` part is parsed with
cli.build_parser() instead. `python3 tests/test_docs.py --external` checks external links (the weekly links workflow).
"""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import cli  # noqa: E402
import gf_profiles  # noqa: E402

README = ROOT / "README.md"
DOCS = [README, *sorted((ROOT / "docs").glob("*.md"))]  # docs/plan/ is not user documentation
LINKED = DOCS + [ROOT / "SECURITY.md", ROOT / "OBSERVABILITY.md", *sorted((ROOT / "skill" / "references").glob("*.md"))]
SHELL = {"bash", "sh", "shell"}
MARK = re.compile(r"\s+#\s*needs-([a-z]+)\s*$")
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
CONTROL = {"|", "||", "&&", ";"}

# Python child processes get this on PYTHONPATH: only loopback connections and lookups are allowed.
BLOCK_NETWORK = '''
import socket
_LOCAL = {"127.0.0.1", "::1", "localhost", None}
_connect, _connect_ex, _gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def _check(sock, addr):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and addr[0] not in _LOCAL:
        raise OSError(101, "network blocked by tests/test_docs.py")
socket.socket.connect = lambda s, a, *r: (_check(s, a), _connect(s, a, *r))[1]
socket.socket.connect_ex = lambda s, a, *r: (_check(s, a), _connect_ex(s, a, *r))[1]
def _getaddrinfo(host, *a, **k):
    if host not in _LOCAL:
        raise socket.gaierror(-2, "network blocked by tests/test_docs.py")
    return _gai(host, *a, **k)
socket.getaddrinfo = _getaddrinfo
'''


def shell_commands(path):
    """[(line, marker or None)] for every command in the file's bash blocks, continuations joined, comments dropped."""
    out = []
    for m in FENCE.finditer(path.read_text(encoding="utf-8")):
        if m.group(1) not in SHELL:
            continue
        for line in re.sub(r"\\\n\s*", " ", m.group(2)).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                mark = MARK.search(line)
                out.append((MARK.sub("", line), mark.group(1) if mark else None))
    return out


def greenfield_argvs(line):
    """The argument lists given to `greenfield` (or greenfield.py) in a shell line."""
    tokens, out = shlex.split(line), []
    for i, t in enumerate(tokens):
        if t == "greenfield" or t.endswith("/greenfield.py"):
            rest = tokens[i + 1:]
            out.append(rest[:next((j for j, r in enumerate(rest) if r in CONTROL), len(rest))])
    return out


def strip_code(text):
    return re.sub(r"`[^`\n]*`", "", FENCE.sub("", text))


def slug(heading):
    return re.sub(r"[^\w\- ]", "", re.sub(r"`", "", heading).strip().lower()).replace(" ", "-")


def anchors(path):
    seen, out = {}, set()
    for h in re.findall(r"^#{1,6} (.+)$", FENCE.sub("", path.read_text(encoding="utf-8")), re.M):
        s = slug(h)
        out.add(s if s not in seen else f"{s}-{seen[s]}")
        seen[s] = seen.get(s, 0) + 1
    return out


def links(path):
    return re.findall(r"\]\(([^)\s]+)\)", strip_code(path.read_text(encoding="utf-8")))


class DocCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name).resolve()
        (base / "bin").mkdir()
        (base / "site").mkdir()
        (base / "site" / "sitecustomize.py").write_text(BLOCK_NETWORK, encoding="utf-8")
        shim = base / "bin" / "greenfield"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -B "{ROOT / "skill" / "scripts" / "greenfield.py"}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        cls.base = base
        cls.env = {**os.environ, "PATH": f"{base / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}", "PYTHONPATH": str(base / "site"),
                   "PYTHONDONTWRITEBYTECODE": "1", "BROWSER": "true", "NO_COLOR": "1", "GREENFIELD_NO_DEPRECATION": "1"}
        for k in ("XDG_CONFIG_HOME", "GF_CONFIG_DIR", "GF_ATTEST_KEY_FILE"):
            cls.env.pop(k, None)

    def fresh_repo(self, name):
        repo, home = self.base / name / "repo", self.base / name / "home"
        repo.mkdir(parents=True)
        home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=30)
        return repo, {**self.env, "HOME": str(home)}

    def run_dashboard(self, line, repo, env):
        """Serve until it answers, then stop it: the dashboard runs until Ctrl-C."""
        argv = shlex.split(line) + ([] if "--port" in line else ["--port", "0"])  # 0: never collide with a dashboard you have open
        with subprocess.Popen(argv, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            try:
                url = json.loads(proc.stdout.readline() or "{}").get("url")
                self.assertTrue(url, proc.stderr.read() if proc.poll() is not None else "no URL printed")
                with urllib.request.urlopen(url + "/api/runs", timeout=10) as r:
                    self.assertEqual(r.status, 200)
            finally:
                proc.terminate()

    def run_doc(self, path):
        repo, env = self.fresh_repo(path.stem)
        parser, ran = cli.build_parser(), 0
        for line, mark in shell_commands(path):
            with self.subTest(file=path.name, command=line):
                if mark:
                    for argv in greenfield_argvs(line):
                        try:
                            with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
                                parser.parse_args(argv)
                        except SystemExit as e:
                            if e.code:  # --version and --help exit 0
                                self.fail(f"does not parse: {err.getvalue().strip()}")
                    continue
                tokens = shlex.split(line)
                if tokens[:1] == ["greenfield"] and "dashboard" in tokens:
                    self.run_dashboard(line, repo, env)
                else:
                    r = subprocess.run(["bash", "-c", line], cwd=repo, env=env, capture_output=True, text=True, timeout=120)
                    # doctor exits 1 by design when a check fails (for example in a repo with nothing installed yet).
                    ok = (0, 1) if tokens[:2] == ["greenfield", "doctor"] else (0,)
                    self.assertIn(r.returncode, ok, f"exit {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
                    self.assertNotIn("Traceback", r.stderr)
                ran += 1
        return repo, ran

    def test_readme_quickstart_reaches_research_incomplete(self):
        repo, ran = self.run_doc(README)
        self.assertGreater(ran, 0)
        decisions = list((repo / "research" / "greenfield").glob("*/decision.json"))
        self.assertEqual(len(decisions), 1)
        self.assertEqual(json.loads(decisions[0].read_text())["decision"], "RESEARCH_INCOMPLETE")

    def test_every_docs_page_runs(self):
        for path in DOCS[1:]:
            self.run_doc(path)


class TroubleshootingTests(unittest.TestCase):
    def test_every_doctor_check_id_is_documented(self):
        import gf_doctor
        ids = set(re.findall(r'_r\(\s*"([a-z_.]+)"', Path(gf_doctor.__file__).read_text(encoding="utf-8")))
        text = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        self.assertGreater(len(ids), 10)
        self.assertEqual([i for i in sorted(ids) if f"### `{i}`" not in text], [])


class ReadmeShapeTests(unittest.TestCase):
    def test_readme_is_short_and_quickstart_is_at_most_six_commands(self):
        text = README.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 150)
        quick = re.search(r"^## Quickstart\n(.*?)^### Output", text, re.S | re.M).group(1)
        shell = sum(len(b.strip().splitlines()) for lang, b in FENCE.findall(quick) if lang in SHELL)
        self.assertLessEqual(shell + 1, 6)  # + the one agent invocation (Claude Code or Codex)
        self.assertNotIn("docs/plan", text)

    def test_scoring_page_matches_the_profiles(self):
        text = (ROOT / "docs" / "how-scoring-works.md").read_text(encoding="utf-8")
        pillars = ["problem", "market", "value", "economics", "distribution", "competition", "execution", "timing"]
        for name, p in gf_profiles.PROFILES.items():
            with self.subTest(profile=name):
                row = f"| `{name}` | " + " | ".join(str(p["weights"][x]) for x in pillars) + " | " + ", ".join(f"`{g}`" for g in p["pilot_gates"])
                self.assertIn(row, text)


class QuotingTests(unittest.TestCase):
    def test_no_dollar_inside_double_quotes(self):  # W53: "4 of 30 paid $49" would lose $49 to the shell
        for path in DOCS:
            for line, _ in shell_commands(path):
                with self.subTest(file=path.name, command=line):
                    self.assertIsNone(re.search(r'"[^"]*(?<!\\)\$[^"]*"', line), "single-quote text that contains $")


class LinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        for path in LINKED:
            for target in links(path):
                if re.match(r"[a-z]+:", target):
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), link=target):
                    file, _, anchor = target.partition("#")
                    dest = (path.parent / file).resolve() if file else path
                    self.assertTrue(dest.exists(), f"{dest} does not exist")
                    if anchor:
                        self.assertIn(anchor, anchors(dest))


def external_links():
    return sorted({t for p in LINKED for t in links(p) if t.startswith(("http://", "https://"))}
                  | {t for p in LINKED for t in re.findall(r"<(https?://[^>\s]+)>", strip_code(p.read_text(encoding="utf-8")))})


def check_external():
    """Print each external link that fails; exit 1 if any did."""
    broken = []
    for url in external_links():
        req = urllib.request.Request(url, headers={"User-Agent": "greenfield-docs-link-check"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status >= 400:
                    broken.append(f"- {url}: HTTP {r.status}")
        except Exception as e:  # any failure is a broken link for the report
            broken.append(f"- {url}: {e}")
    print("\n".join(broken) if broken else "All external links answered.")
    return 1 if broken else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--external"]:
        raise SystemExit(check_external())
    unittest.main()
