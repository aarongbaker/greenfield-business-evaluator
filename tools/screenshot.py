#!/usr/bin/env python3
"""Developer script: capture docs/mission-control.png from `greenfield demo` with Playwright (test-only dependency).

The PNG's sidecar docs/mission-control.png.sha256 records the sha256 of skill/assets/mission-control.html it was taken
from. `--check` needs no browser: it exits 1 when the dashboard HTML changed since the last capture.
"""
from pathlib import Path
import argparse
import hashlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "skill" / "assets" / "mission-control.html"
PNG = ROOT / "docs" / "mission-control.png"
STAMP = PNG.with_name(PNG.name + ".sha256")
CLI = [sys.executable, "-B", str(ROOT / "skill" / "scripts" / "greenfield.py")]


def html_hash():
    return hashlib.sha256(HTML.read_bytes()).hexdigest()


def capture():
    from playwright.sync_api import sync_playwright  # shortcut: test-only dependency, imported only when capturing
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(CLI + ["--project", tmp, "demo"], check=True, capture_output=True, timeout=60)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = subprocess.Popen(CLI + ["--project", tmp, "dashboard", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            url = f"http://127.0.0.1:{port}/"
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "api/runs", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light", device_scale_factor=1)
                page.goto(url)
                end = time.monotonic() + 15  # poll from Python: the dashboard CSP forbids wait_for_function's eval
                while not page.evaluate("document.querySelectorAll('#feed .row').length > 0 && document.getElementById('vword').textContent.length > 0"):
                    if time.monotonic() > end:
                        raise SystemExit("dashboard did not render the demo run")
                    time.sleep(0.1)
                page.wait_for_timeout(500)
                PNG.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(PNG))
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
    STAMP.write_text(html_hash() + "  skill/assets/mission-control.html\n", encoding="utf-8")
    print("wrote", PNG.relative_to(ROOT))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the screenshot predates the current dashboard HTML")
    args = ap.parse_args(argv)
    if args.check:
        ok = PNG.is_file() and STAMP.is_file() and STAMP.read_text(encoding="utf-8").split()[0] == html_hash()
        if not ok:
            print("stale: docs/mission-control.png (run python3 tools/screenshot.py with Playwright installed)", file=sys.stderr)
        return 0 if ok else 1
    capture()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
