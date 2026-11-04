"""SECURITY.md must name only files and tests that exist, and every Defended row must name a test (W30)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')
TEST_SOURCES = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT / 'tests').glob('test_*.py'))
TOKENS = set(re.findall(r'`([^`\s]+)`', TEXT))


class SecurityDocTests(unittest.TestCase):
    def test_named_tests_exist(self):
        names = {t.split('::')[-1] for t in TOKENS if re.fullmatch(r'(\w+\.py::)?test_\w+', t)}
        self.assertTrue(names)
        for name in sorted(names):
            self.assertRegex(TEST_SOURCES, rf'def {name}\(', name)

    def test_named_test_files_exist(self):
        files = {t.split('/')[-1] for t in TOKENS if re.fullmatch(r'(tests/)?test_\w+\.py', t)}
        self.assertTrue(files)
        for name in sorted(files):
            self.assertTrue((ROOT / 'tests' / name).is_file(), name)

    def test_named_source_paths_exist(self):
        paths = {t for t in TOKENS if re.fullmatch(r'(skill|tools|platform|tests)/[\w./-]+', t)}
        self.assertTrue(paths)
        for rel in sorted(paths):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_named_function_exists(self):
        self.assertIn('`resolve_inside()`', TEXT)
        self.assertRegex((ROOT / 'skill/scripts/gf_common.py').read_text(encoding='utf-8'), r'def resolve_inside\(')

    def test_every_defended_row_names_a_test(self):
        rows = [r.split('|')[1:-1] for r in TEXT.splitlines() if r.startswith('| ') and r.count('|') == 5]
        defended = [r for r in rows if r[1].strip().startswith('Defended')]
        self.assertGreaterEqual(len(defended), 5)
        for threat, status, how, proof in (tuple(c.strip() for c in r) for r in defended):
            self.assertIn('test_', proof, threat)

    def test_reporting_and_no_invented_contact(self):
        self.assertIn('security/advisories/new', TEXT)
        self.assertNotRegex(TEXT, r'[\w.+-]+@[\w-]+\.[\w.]+')


if __name__ == '__main__':
    unittest.main()
