"""Wave 3 gate: Mission Control in a real browser.

Skips when Playwright is not importable; GF_REQUIRE_BROWSER=1 (set in CI) turns that skip into a failure.
GF_SCREENSHOT_DIR, when set, receives 1440 and 390px screenshots in both themes.
"""
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gf_observe as observe  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
REQUIRE = os.environ.get("GF_REQUIRE_BROWSER") == "1"
SHOTS = os.environ.get("GF_SCREENSHOT_DIR")
FIRST_VISIBLE = """() => {const f=document.getElementById('feed');
  return [...f.children].find(n => !n.hidden && n.offsetTop + n.offsetHeight > f.scrollTop + 1)}"""


def wait(page, expr, timeout=10000):
    """Poll a JS expression from Python: wait_for_function would eval() inside the page, which the dashboard CSP forbids."""
    end = time.monotonic() + timeout / 1000
    while not page.evaluate(expr):
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {expr}")
        time.sleep(0.1)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(sync_playwright is None and not REQUIRE, "playwright not installed")
class DashboardBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise AssertionError("GF_REQUIRE_BROWSER=1 but playwright is not importable")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = root = Path(cls.tmp.name).resolve()
        cli = lambda *a: subprocess.run([sys.executable, str(SCRIPTS / "gf_observe.py"), *a, "--project", str(root)],
                                        capture_output=True, text=True, timeout=60, check=True).stdout.strip()
        cls.demo = cli("demo")
        for i in range(60):  # enough rows to scroll the feed
            observe.emit(root, cls.demo, "note", summary=f"Seed note {i}")
        observe.emit(root, cls.demo, "warning", agent="gf-market", summary="Seed warning")
        # A finished real run with >10,000 events and a forged decision.json (the H3 replay).
        folder = root / "research" / "greenfield" / "laundry"
        folder.mkdir(parents=True)
        (folder / "evaluation.json").write_text((ROOT / "skill/assets/demo-research/evaluation.json").read_text())
        (folder / "decision.json").write_text(json.dumps({"decision": "PROCEED_TO_BOUNDED_PILOT", "weighted_quality_0_to_100": 90, "evidence_average_0_to_5": 4}))
        cls.big = observe.new_run(root, "Forged and long", "claude", research_dir="research/greenfield/laundry")
        observe.emit(root, cls.big, "agent_started", provider="claude", agent="gf-market")
        line = json.dumps({"event": "tool_started", "agent": "gf-market", "tool": "WebSearch", "timestamp": observe.now(), "provider": "claude"}) + "\n"
        with observe.file_paths(root, cls.big)[1].open("a") as f:
            f.write(line * 10001)
        observe.emit(root, cls.big, "run_completed")
        cls.port = free_port()
        cls.url = f"http://127.0.0.1:{cls.port}/"
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch()
        cls.addClassCleanup(cls.browser.close)
        cls.start_server()
        cls.addClassCleanup(lambda: (cls.server.terminate(), cls.server.wait(timeout=10)))

    @classmethod
    def start_server(cls):
        cls.server = subprocess.Popen([sys.executable, str(SCRIPTS / "gf_observe.py"), "serve", "--project", str(cls.root), "--port", str(cls.port)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + "api/runs", timeout=1).close()
                return
            except OSError:
                time.sleep(0.1)
        cls.server.kill()
        cls.server.wait(timeout=10)
        raise AssertionError("server did not start")

    def open(self, run=None, **ctx):
        context = self.browser.new_context(**ctx)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(self.url + (f"#run={run or self.demo}"))
        wait(page, "document.getElementById('vword').textContent.length > 0", timeout=15000)
        wait(page, "document.querySelectorAll('#feed .row').length > 0", timeout=15000)
        return page, errors

    def test_a_demo_run_shows_decision_panel(self):
        page, errors = self.open()
        self.assertEqual(page.text_content("#vword"), "Validate before build")
        self.assertEqual(page.locator("#pillars tr").count(), 8)
        self.assertEqual(page.locator("#pbar [data-p]").count(), 8)  # the score split by pillar
        self.assertEqual(page.locator("#graph .node").count(), 11)  # orchestrator, 8 specialists, red team, verdict
        self.assertTrue(page.is_visible('#graph [data-agent="gf-redteam"]'))
        self.assertTrue(page.is_hidden("#lanebox"))
        # next steps as a path: the first test is open with its five rooms, and the room to do next is marked
        self.assertEqual(page.get_attribute('#pathBody .mnode[aria-current="step"]', "aria-pressed"), "true")
        self.assertEqual(page.locator("#pathBody .room").count(), 5)
        self.assertEqual(page.text_content('#pathBody .room[aria-current="true"]').strip(), "Send and track")
        page.click('#pathBody [data-room="find"]')
        self.assertIn("prospects.csv", page.text_content("#pathBody .prompt"))
        self.assertTrue(page.evaluate("document.activeElement.dataset.room === 'find'"))
        self.assertTrue(page.is_hidden("#betbox"))
        self.assertIn("Next: test 1 of 3.", page.text_content("#mapbox"))
        self.assertTrue(page.is_hidden("#banner"))
        self.assertTrue(page.is_visible("#demoTag"))
        texts = page.evaluate("[document.body.innerText, ...[...document.querySelectorAll('option')].map(o => o.textContent)]")
        for line in "\n".join(texts).splitlines():
            self.assertLessEqual(line.count("DEMO"), 1, line)
        self.assertEqual(errors, [])

    def test_b_focus_and_feed_scroll_survive_two_refreshes(self):
        page, _ = self.open()
        statuses = []
        page.on("response", lambda r: "/api/state" in r.url and statuses.append(r.status))
        page.focus('#graph [data-agent="gf-market"]')  # the graph is the default view
        page.evaluate("window._row = document.activeElement; document.getElementById('feed').scrollTop = 400")
        page.wait_for_timeout(300)
        page.evaluate(f"window._first = ({FIRST_VISIBLE})()")
        for batch in range(2):
            for i in range(5):
                observe.emit(self.root, self.demo, "note", summary=f"Refresh {batch}.{i}")
            wait(page, f"document.getElementById('newPill').textContent === '{5 * (batch + 1)} new events ↓'", timeout=10000)
        self.assertTrue(page.evaluate("document.activeElement === window._row"))
        self.assertTrue(page.evaluate(f"({FIRST_VISIBLE})() === window._first"))
        # No new events: polls answer 304 and the page leaves the log and pillars alone (lanes and clocks tick every second while running).
        page.evaluate("window._muts = 0; const o = new MutationObserver(m => window._muts += m.length); for (const id of ['feed', 'pillars', 'vword', 'missing']) o.observe(document.getElementById(id), {subtree: true, childList: true, attributes: true, characterData: true})")
        statuses.clear()
        page.wait_for_timeout(4500)
        self.assertGreaterEqual(statuses.count(304), 2, statuses)
        self.assertNotIn(200, statuses)
        self.assertEqual(page.evaluate("window._muts"), 0)

    def test_c_filter_persists_across_reload(self):
        page, _ = self.open()
        page.click('[data-f="warn"]')
        self.assertIn("f=warn", page.evaluate("location.hash"))
        visible = "[...document.querySelectorAll('#feed .row')].filter(n => !n.hidden).length"
        self.assertEqual(page.evaluate(visible), 2)  # the demo's sample fetch timeout and the seeded warning
        page.reload()
        wait(page, "document.querySelectorAll('#feed .row').length > 0", timeout=15000)
        self.assertEqual(page.get_attribute('[data-f="warn"]', "aria-pressed"), "true")
        self.assertEqual(page.evaluate(visible), 2)

    def test_d_no_overflow_and_12px_floor(self):
        for scheme in ("light", "dark"):
            for width in (390, 1440):
                page, errors = self.open(viewport={"width": width, "height": 900}, color_scheme=scheme)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width, (scheme, width))
                # the verdict and the live lanes share the first screen on desktop and stack on a phone
                tops = page.evaluate("['verdict', 'lh'].map(id => document.getElementById(id).closest('section').offsetTop)")
                self.assertEqual(len(set(tops)), 1 if width == 1440 else 2, (scheme, width, tops))
                # SVG text scales with the map, so check its rendered height, not its CSS size
                tiny = page.evaluate("[...document.querySelectorAll('#map text')].filter(t => t.getBoundingClientRect().height && t.getBoundingClientRect().height < 12).length")
                self.assertEqual(tiny, 0, (scheme, width))
                small = page.evaluate("""[...document.querySelectorAll('body *')].filter(el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
                    && el.getClientRects().length && parseFloat(getComputedStyle(el).fontSize) < 12).map(el => el.className || el.tagName)""")
                self.assertEqual(small, [], (scheme, width))
                self.assertEqual(errors, [])
                if SHOTS:
                    page.screenshot(path=str(Path(SHOTS) / f"mission-control-{width}-{scheme}.png"), full_page=True)

    def test_e_blocked_storage_still_renders(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        context.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked') }})")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(self.url + f"#run={self.demo}")
        wait(page, "document.getElementById('vword').textContent.length > 0", timeout=15000)
        page.click("#theme")
        self.assertEqual(errors, [])

    def test_f_pillar_drill_down(self):
        page, _ = self.open()
        page.click('#pillars [data-p="economics"]')
        wait(page, "document.getElementById('ev-economics').textContent.includes('C4')", timeout=5000)
        self.assertIn("Not checked yet", page.text_content("#ev-economics"))
        self.assertIn("open", page.get_attribute("#drawer", "class"))
        page.keyboard.press("Escape")
        self.assertNotIn("open", page.get_attribute("#drawer", "class"))

    def test_g_forged_decision_and_long_run(self):
        page, _ = self.open(run=self.big)
        self.assertIn("decision.json says Proceed to bounded pilot", page.text_content("#banner"))
        self.assertEqual(page.text_content("#vword"), "Validate before build")
        self.assertTrue(page.text_content("#runKind").startswith("completed"))
        wait(page, "document.getElementById('connText').textContent.startsWith('finished')", timeout=5000)
        self.assertEqual(page.get_attribute('#graph [data-agent="gf-market"] .g', "title"), "Done")
        # a finished run folds the panel to one line; the timeline behind it is still drawn
        self.assertTrue(page.text_content("#laneDoneText").startswith("Research finished in "))
        self.assertTrue(page.is_hidden("#graph"))
        page.click("#laneToggle")
        page.click('#viewSw [data-v="timeline"]')
        self.assertTrue(page.is_visible('#agents [data-agent="gf-market"]'))
        self.assertEqual(page.get_attribute('#agents [data-agent="gf-market"] .g', "title"), "Done")
        self.assertNotIn("Running", page.locator('#agents [data-agent="gf-market"]').inner_text())
        # frozen timeline: the running agent's bar ends exactly where the last event (run_completed) sits on the scale
        s = json.load(urllib.request.urlopen(f"{self.url}api/state?run={self.big}"))
        t0, t1 = (dt.datetime.fromisoformat(s["run_window"][k]).timestamp() for k in ("start", "end"))
        want = (t1 - t0) / max(5, t1 - t0) * 100
        got = page.evaluate("(() => { const f = document.querySelector('#agents [data-agent=\"gf-market\"] .span'); return parseFloat(f.style.left) + parseFloat(f.style.width) })()")
        self.assertAlmostEqual(got, want, delta=0.1)
        self.assertEqual(s["run_window"]["end"], s["events"][0]["timestamp"])

    def test_z_disconnect_shows_red_pill(self):
        page, _ = self.open()
        self.server.terminate()
        self.server.wait(timeout=10)
        try:
            wait(page, "document.getElementById('connText').textContent.startsWith('offline')", timeout=6000)
            self.assertIn("bad", page.get_attribute("#conn", "class"))
            self.assertTrue(page.is_visible("#retry"))
        finally:
            type(self).start_server()


if __name__ == "__main__":
    unittest.main()
