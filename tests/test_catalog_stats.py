"""Catálogo sem PSdZData inteira (varredura de pasta) e amostrador de estatísticas."""
import os, sys, shutil, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import catalog, stats

class CatalogTest(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.mkdtemp()
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)
    def touch(self, rel):
        p = os.path.join(self.tmp, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()

    def test_catalog_without_psdz(self):
        c = catalog.build_catalog(None)
        self.assertFalse(c['psdz_ok'])
        self.assertTrue(c['series'] and c['generations'])
        self.assertEqual([r['id'] for r in c['roles'][:2]], ['0000271a', '00002720'])
        self.assertTrue(all(r['files'] == [] for r in c['roles']))
        self.assertEqual([g['id'] for g in c['generations'] if g['supported']], ['id6', 'id5', 'id4', 'id7', 'id8'])

    def test_scan_nested_and_versions(self):
        for f in ('swfl_0000271a.bin.007_051_002', 'swfl_00002719.bin.007_039_008', 'swfl_00002719.bin.007_051_002', 'swfl_99999999.bin.001_001_001', 'swfl_00002720.bin.bak'):
            self.touch('x/y/z/' + f)
        r = catalog.scan_folder(self.tmp, ['0000271A', '00002719', '00002720'])
        v = {k: [f['version'] for f in fs] for k, fs in r['files'].items()}
        self.assertEqual(v, {'0000271a': ['007_051_002'], '00002719': ['007_051_002', '007_039_008'], '00002720': []})

    def test_scan_psdz_layout_shortcut(self):
        self.touch('psdzdata/swe/swfl/swfl_00002720.bin.007_051_002')
        r = catalog.scan_folder(self.tmp, ['00002720'])
        self.assertEqual(len(r['files']['00002720']), 1)

class StatsTest(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(stats._cputime('1:02.50'), 62.5)
        self.assertEqual(stats._cputime('1:00:01'), 3601.0)
        self.assertIsNone(stats._cputime('x'))
        self.assertEqual(stats.percentile([1, 2, 3, 4, 5], .95), 5)
        self.assertEqual(stats.percentile([], .5), 0.0)

    def test_ps_info_self(self):
        row = stats.ps_info([os.getpid()])[os.getpid()]
        self.assertGreater(row[1], 0)       # RSS

    def test_snapshot_idle_and_storage(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, 'env1', 'images')); open(os.path.join(tmp, 'env1', 'images', 'a.img'), 'wb').write(b'0' * 4096)
            open(os.path.join(tmp, 'env1', 'env.json'), 'w').write('{}')
            app = type('A', (), {'rt': None})()
            s = stats.Sampler(app, lambda eid: os.path.join(tmp, eid))
            try:
                snap = s.snapshot('env1')
                self.assertFalse(snap['running']); self.assertEqual(snap['samples'], [])
                parts = {p['id']: p['bytes'] for p in snap['storage']['parts']}
                self.assertEqual(parts['images'], 4096); self.assertEqual(parts['other'], 2)
                self.assertGreater(snap['static']['host_ram_mb'], 0)
            finally: s.stop()
        finally: shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__': unittest.main()


class PackagesTest(unittest.TestCase):
    def test_stage_and_status(self):
        import tempfile
        from idemu import catalog
        with tempfile.TemporaryDirectory() as tmp:
            old = (catalog.STAGE, catalog.load_settings); catalog.STAGE = os.path.join(tmp, 'stage'); catalog.load_settings = lambda: {}
            try:
                self.assertFalse(catalog.packages_ok('mgu22'))
                req = catalog.required_packages('mgu22')
                for r in req:
                    f = os.path.join(tmp, '{prefix}_{id}.bin.{version}'.format(**r)); open(f, 'wb').write(b'x')
                    self.assertTrue(catalog.stage_file(f, 'mgu22')[0])
                self.assertTrue(catalog.packages_ok('mgu22'))
                bad = os.path.join(tmp, 'swfl_%s.bin.001_001_001' % req[0]['id']); open(bad, 'wb').write(b'x')
                self.assertFalse(catalog.stage_file(bad, 'mgu22')[0])
                self.assertFalse(catalog.stage_file(os.path.join(tmp, 'x.txt'), 'mgu22')[0])
                self.assertEqual(catalog.effective_psdz('mgu22'), catalog.STAGE)
            finally: catalog.STAGE, catalog.load_settings = old
