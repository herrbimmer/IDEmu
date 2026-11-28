"""MGU22 firmware discovery and staging with empty package fixtures."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from idemu import catalog


class Mgu22FirmwareTest(unittest.TestCase):
    default, alternate = catalog.MGU22_VERSIONS

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.psdz = self.root / 'psdzdata'
        self.stage = self.root / 'packages'
        for patcher in (mock.patch.object(catalog, 'STAGE', str(self.stage)),
                        mock.patch.object(catalog, 'load_settings', return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_firmware(self, version, *, prefix=None):
        for item in catalog.required_packages('mgu22', version):
            folder = self.psdz / 'swe' / item['prefix']
            if prefix is None or item['prefix'] == prefix:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / '{prefix}_{id}.bin.{version}'.format(**item)).touch()

    def test_complete_alternate_and_preferred_default(self):
        self.add_firmware(self.alternate)
        status = catalog.package_status('mgu22', str(self.root))
        self.assertEqual((status['version'], status['have'], status['ok']), (self.alternate, 6, True))
        self.assertEqual(catalog.mgu22_firmware(str(self.root))[0], str(self.psdz))
        self.add_firmware(self.default)
        self.assertEqual(catalog.package_status('mgu22', str(self.root))['version'], self.default)

    def test_mixed_swfl_and_swfk_do_not_make_a_valid_set(self):
        self.add_firmware(self.alternate, prefix='swfl')
        self.add_firmware(self.default, prefix='swfk')
        status = catalog.package_status('mgu22', str(self.psdz))
        self.assertEqual((status['have'], status['total'], status['ok']), (3, 6, False))

    def test_scan_and_manual_pick_stage_both_package_types(self):
        self.add_firmware(self.alternate)
        swfk = next((self.psdz / 'swe' / 'swfk').iterdir())
        self.assertTrue(catalog.stage_file(str(swfk), 'mgu22')[0])
        result = catalog.stage_mgu22_folder(str(self.root))
        self.assertEqual((result['version'], result['have'], result['staged']), (self.alternate, 6, 5))
        self.assertEqual(catalog.effective_psdz('mgu22'), str(self.stage))
        self.assertTrue(catalog.stage_file(str(self.stage / 'swe' / 'swfk' / swfk.name), 'mgu22')[0])


if __name__ == '__main__':
    unittest.main()
