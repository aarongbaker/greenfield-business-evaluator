"""W11: attested events need a person at a terminal and a local HMAC key."""
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill/scripts"
sys.path.insert(0, str(SCRIPTS))
import gf_ledger as ledger
from test_skill import attest, proceed_data, scorer, write_event

LEDGER_CLI = str(SCRIPTS / "gf_ledger.py")


def run_on_pty(argv, env, answer):
    """Run python argv on a fresh pseudo-terminal, type answer(code) at the prompt; return (exit code, output)."""
    pid, fd = pty.fork()
    if pid == 0:  # child: exec at once
        os.execve(sys.executable, [sys.executable, *argv], env)
    out, sent = b"", False
    try:
        while select.select([fd], [], [], 10)[0]:
            try:
                chunk = os.read(fd, 1024)
            except OSError:  # EIO once the child exits
                break
            if not chunk:
                break
            out += chunk
            if not sent and b"Type the code" in out:
                code = re.search(rb"Confirmation code: (\w{6})", out).group(1).decode()
                os.write(fd, (answer(code) + "\n").encode())
                sent = True
    finally:
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


def rewrite(path, edit):
    """Apply edit(event) to each event and recompute the (unkeyed) hash chain, as a forger would."""
    prev, lines = "GENESIS", []
    for line in Path(path).read_text().splitlines():
        event = json.loads(line)
        event.pop("hash")
        edit(event)
        event["previous_hash"] = prev
        event["hash"] = prev = ledger.digest(event)
        lines.append(ledger.canonical(event))
    Path(path).write_text("\n".join(lines) + "\n")


class AttestationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "receipt.txt").write_text("SYNTHETIC TEST RECEIPT")
        self.ledger = self.root / "ledger.jsonl"
        self.cfg = self.root / "cfg"
        self.env = dict(os.environ, GF_CONFIG_DIR=str(self.cfg))
        self.env.pop("GF_ATTEST_KEY_FILE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def record_args(self):
        return [LEDGER_CLI, "record", "--ledger", str(self.ledger), "--kind", "paid_test", "--project", "X", "--hypothesis", "H",
                "--artifact", str(self.root / "receipt.txt"), "--attester", "Jane Human", "--pillar", "problem"]

    def test_library_append_without_tty_refused(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import gf_ledger\n"
                "try: gf_ledger.append(sys.argv[2], 'paid_test', 'X', 'H', artifact='receipt.txt', attester='Jane Human')\n"
                "except ValueError as e: print(e)")
        proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(self.ledger)], env=self.env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, start_new_session=True)
        self.assertIn(ledger.NO_TTY, proc.stdout)
        self.assertFalse(self.ledger.exists())
        self.assertFalse(self.cfg.exists())

    def test_handwritten_ledger_not_verified(self):
        meta = ledger.artifact_digest("receipt.txt", self.root)
        event = write_event(self.ledger, meta)  # human_attested true, correct SHA-256, no key
        ok, why = ledger.verified_behavior(self.ledger, event["id"])
        self.assertFalse(ok)
        self.assertEqual(why, "receipt is unsigned (recorded before v2.1)")
        data = proceed_data(event["id"], "ledger.jsonl")
        errors, warnings = scorer.validate(data, self.root)
        self.assertFalse(errors, errors)
        self.assertEqual(scorer.score(data, warnings)["decision"], "VALIDATE_BEFORE_BUILD")
        self.assertTrue(any("gf_ledger.py reattest" in w for w in warnings), warnings)

    def test_cli_record_requires_tty(self):
        proc = subprocess.run([sys.executable, *self.record_args()], env=self.env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, start_new_session=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(ledger.NO_TTY, proc.stderr)
        self.assertFalse(self.ledger.exists())
        status, out = run_on_pty(self.record_args(), self.env, lambda code: code)
        self.assertEqual(status, 0, out)
        self.assertIn("Created attestation key", out)
        event = ledger.read_ledger(self.ledger)[0]
        self.assertTrue(event["sig"].startswith("v1:"))
        self.assertEqual(event["artifact"]["path"], "receipt.txt")
        with mock.patch.dict(os.environ, GF_CONFIG_DIR=str(self.cfg)):
            self.assertTrue(ledger.verified_behavior(self.ledger, event["id"], "problem")[0])

    def test_wrong_code_writes_nothing(self):
        status, out = run_on_pty(self.record_args(), self.env, lambda code: "ZZZZZZ" if code != "ZZZZZZ" else "YYYYYY")
        self.assertEqual(status, 2, out)
        self.assertIn("did not match", out)
        self.assertFalse(self.ledger.exists())
        self.assertFalse((self.cfg / "attest.key").exists())

    def test_key_permissions(self):
        with mock.patch.dict(os.environ, GF_CONFIG_DIR=str(self.cfg / "greenfield")):
            path, created = ledger.ensure_key()
            self.assertTrue(created)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(path.read_bytes()), 32)
            self.assertEqual(ledger.ensure_key(), (path, False))

    def test_tampered_signed_event_fails(self):
        event = attest(self.ledger, "paid_test", "X", "H", artifact="receipt.txt", attester="Jane Human", pillars=["problem"])
        self.assertTrue(ledger.verified_behavior(self.ledger, event["id"])[0])
        for field, value in (("outcome", "paid 10x"), ("attester", "Someone Else"), ("seq", 1), ("pillar_ids", ["problem", "market"])):
            with self.subTest(field=field):
                original = self.ledger.read_text()
                rewrite(self.ledger, lambda e: e.update({field: value}) if field != "seq" else None)
                if field == "seq":  # move the event: insert an unsigned note before it
                    lines = self.ledger.read_text().splitlines()
                    self.ledger.unlink()
                    ledger.append(self.ledger, "note", "X", "inserted")
                    with self.ledger.open("a") as f:
                        f.write("\n".join(lines) + "\n")
                    rewrite(self.ledger, lambda e: e.update(seq=2) if e["id"] == event["id"] else None)
                self.assertEqual(ledger.verified_behavior(self.ledger, event["id"]),
                                 (False, "signature does not match: the event was edited"))
                self.ledger.write_text(original)

    def test_rotated_key_fails_with_reason(self):
        event = attest(self.ledger, "paid_test", "X", "H", artifact="receipt.txt", attester="Jane Human", pillars=list(scorer.CORE))
        old_key = ledger.key_path()
        with mock.patch.dict(os.environ, GF_CONFIG_DIR=str(self.cfg)):
            self.assertEqual(ledger.verified_behavior(self.ledger, event["id"]), (False, "no attestation key on this machine"))
            ledger.ensure_key()
            self.assertEqual(ledger.verified_behavior(self.ledger, event["id"]),
                             (False, f"signed with a different key (key {event['key_id']})"))
            data = proceed_data(event["id"], "ledger.jsonl")
            errors, warnings = scorer.validate(data, self.root)
            self.assertFalse(errors, errors)
            self.assertEqual(scorer.score(data, warnings)["decision"], "VALIDATE_BEFORE_BUILD")
            with mock.patch.dict(os.environ, GF_ATTEST_KEY_FILE=str(old_key)):  # key shared out of band
                self.assertTrue(ledger.verified_behavior(self.ledger, event["id"])[0])

    def test_reattest_restores_legacy_event(self):
        meta = ledger.artifact_digest("receipt.txt", self.root)
        meta["path"] = str(self.root / "receipt.txt")  # legacy events stored absolute paths
        legacy = write_event(self.ledger, meta)
        data = proceed_data(legacy["id"], "ledger.jsonl")
        errors, warnings = scorer.validate(data, self.root)
        self.assertFalse(errors, errors)
        self.assertEqual(scorer.score(data, warnings)["decision"], "VALIDATE_BEFORE_BUILD")
        ledger.ensure_key()
        out = ledger.reattest(self.ledger, confirm=lambda summary: None)
        self.assertEqual([r["action"] for r in out], ["reattested"])
        self.assertEqual(ledger.read_ledger(self.ledger)[-1]["artifact"]["path"], "receipt.txt")
        errors, warnings = scorer.validate(data, self.root)
        self.assertFalse(errors, errors)
        self.assertEqual(scorer.score(data, warnings)["decision"], "PROCEED_TO_BOUNDED_PILOT")
        self.assertEqual(ledger.reattest(self.ledger, confirm=lambda summary: None), [])  # idempotent

    def test_notes_need_no_signature(self):
        def refuse(summary):
            raise AssertionError("notes must not ask for confirmation")
        for kind in ("note", "hypothesis"):
            event = ledger.append(self.ledger, kind, "X", "H", confirm=refuse)
            self.assertNotIn("sig", event)
        self.assertEqual(len(ledger.read_ledger(self.ledger)), 2)


if __name__ == "__main__":
    unittest.main()
