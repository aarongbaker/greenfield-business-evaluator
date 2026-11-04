import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skill/scripts'))
sys.path.insert(0,str(ROOT))
import gf_common as c
from gf_common import GFError
import configure_hooks


class ResolveInsideTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve()/'base';(self.base/'a').mkdir(parents=True)
    def test_inside(self):
        self.assertEqual(c.resolve_inside(self.base,'a/b.json'),self.base/'a/b.json')
    def test_escape(self):
        for bad in ('../x','/etc/passwd'):
            with self.assertRaises(GFError) as e:c.resolve_inside(self.base,bad)
            self.assertIn(str(self.base),str(e.exception))
    def test_symlinks(self):
        (self.base/'out').symlink_to(self.base.parent)
        (self.base/'in').symlink_to(self.base/'a')
        with self.assertRaises(GFError):c.resolve_inside(self.base,'out/x')
        self.assertEqual(c.resolve_inside(self.base,'in/x'),self.base/'a/x')
    def test_empty_and_nul(self):
        for bad in ('','a\x00b'):
            with self.assertRaises(GFError):c.resolve_inside(self.base,bad)
    def test_base_through_symlink(self):
        link=self.base.parent/'link';link.symlink_to(self.base)
        self.assertEqual(c.resolve_inside(link,'a'),self.base/'a')
    def test_must_exist(self):
        self.assertEqual(c.resolve_inside(self.base,'a',must_exist=True),self.base/'a')
        with self.assertRaises(GFError):c.resolve_inside(self.base,'nope',must_exist=True)


class LoadJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'x.json'
    def load(self,text,**kw):
        self.p.write_bytes(text if isinstance(text,bytes) else text.encode());return c.load_json(self.p,**kw)
    def test_over_limit(self):
        with self.assertRaises(GFError) as e:self.load('{"a": 12345}',max_bytes=5)
        self.assertIn('12 bytes',str(e.exception));self.assertIn('5 byte limit',str(e.exception))
    def test_grows_during_read(self):
        self.p.write_text('{"a": 12345}')
        with mock.patch.object(Path,'stat',return_value=SimpleNamespace(st_size=1)):
            with self.assertRaises(GFError) as e:c.load_json(self.p,max_bytes=5)
        self.assertIn('5 byte limit',str(e.exception))
    def test_rejects(self):
        for text,word in (('{"a": NaN}','NaN'),('{"a": Infinity}','Infinity'),('{"a": -Infinity}','Infinity'),('{"a": 1, "a": 2}','duplicate')):
            with self.assertRaises(GFError) as e:self.load(text)
            self.assertIn(word,str(e.exception))
        self.assertEqual(self.load('{"a": 1, "a": 2}',reject_duplicates=False),{'a':2})
    def test_bom(self):
        self.assertEqual(self.load(b'\xef\xbb\xbf{"a": 1}'),{'a':1})
    def test_deep_nesting(self):
        with self.assertRaises(GFError):self.load('['*100000,expect=None)
    def test_wrong_type_and_bad_json(self):
        with self.assertRaises(GFError):self.load('[1]')
        self.assertEqual(self.load('[1]',expect=list),[1])
        with self.assertRaises(GFError) as e:self.load('{\n"a": }')
        self.assertIn('line 2',str(e.exception))


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name);self.p=self.d/'f.json'
    def test_crash_keeps_original(self):
        self.p.write_text('original')
        with mock.patch('os.replace',side_effect=OSError('boom')):
            with self.assertRaises(OSError):c.atomic_write(self.p,'new')
        self.assertEqual(self.p.read_text(),'original');self.assertEqual(os.listdir(self.d),['f.json'])
    def test_modes(self):
        c.atomic_write(self.p,b'x',mode=0o600);self.assertEqual(self.p.stat().st_mode&0o777,0o600)
        os.chmod(self.p,0o640);c.atomic_write(self.p,'y');self.assertEqual(self.p.stat().st_mode&0o777,0o640)
        self.assertEqual(self.p.read_text(),'y')
    def test_new_file_uses_umask(self):
        old=os.umask(0o022)
        try:c.atomic_write(self.p,'x')
        finally:os.umask(old)
        self.assertEqual(self.p.stat().st_mode&0o777,0o644)
    def test_json(self):
        c.atomic_write_json(self.p,{'a':'é'});self.assertEqual(self.p.read_text(encoding='utf-8'),'{\n  "a": "é"\n}\n')
        with self.assertRaises(ValueError):c.atomic_write_json(self.p,{'a':float('nan')})


class FiniteNonnegTests(unittest.TestCase):
    def test_rejects(self):
        for bad in (-1,float('nan'),float('inf'),True,'5',None,[]):
            with self.assertRaises(GFError) as e:c.finite_nonneg(bad,'widgets')
            self.assertIsInstance(e.exception,ValueError);self.assertIn('widgets',str(e.exception))
    def test_accepts(self):
        for v in (0,2,2.5):
            self.assertEqual(c.finite_nonneg(v,'w'),float(v));self.assertIsInstance(c.finite_nonneg(v,'w',limit=10),float)
    def test_limit(self):
        with self.assertRaises(GFError) as e:c.finite_nonneg(11,'w',limit=10)
        self.assertIn('<= 10',str(e.exception))


class ReportTests(unittest.TestCase):
    def test_format(self):
        out=io.StringIO();err=GFError('evaluation.json is not valid JSON',path='a/evaluation.json',hint='fix the file')
        self.assertEqual(c.report(err,stream=out),2)
        self.assertEqual(out.getvalue(),'ERROR: evaluation.json is not valid JSON\n  path: a/evaluation.json\n  next: fix the file\n')
        self.assertEqual(err.as_dict(),{'error':'evaluation.json is not valid JSON','path':'a/evaluation.json','next':'fix the file','code':2})


class ConfigureHooksTests(unittest.TestCase):
    def test_failed_write_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.local.json';p.write_text('{"x": 1}\n')
            with mock.patch('os.replace',side_effect=OSError('boom')):
                with self.assertRaises(OSError):configure_hooks.transform(p,'cmd gf_observe.py hook --project .','install',platform='claude')
            self.assertEqual(p.read_text(),'{"x": 1}\n');self.assertEqual(os.listdir(d),['settings.local.json'])


if __name__=='__main__':
    unittest.main()
