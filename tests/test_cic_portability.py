import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
sys.path.insert(0, ROOT)

import bootinfo                                 # noqa: E402

BUILD_SH = os.path.join(ROOT, 'src', 'cic', 'build.sh')


class RootPasswordTest(unittest.TestCase):
    """O módulo crypt saiu do Python 3.13: a senha padrão do root não pode depender dele."""

    def test_default_password_without_crypt(self):
        with mock.patch.dict(sys.modules, {'crypt': None}):          # simula o Python 3.13+
            old, new = bootinfo.root_password_edit('root')
        self.assertEqual(old, b'KPcKrCeGUgGeA')
        self.assertEqual(new, b'KPNHwB2guYDys')
        self.assertEqual(len(old), len(new))                         # a troca no imagefs é do mesmo tamanho

    def test_default_hash_matches_crypt(self):
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                import crypt
        except ImportError:
            self.skipTest('sem módulo crypt neste Python')
        self.assertEqual(crypt.crypt('root', 'KP').encode(), bootinfo.ROOT_HASH['root'])

    def test_other_password_without_crypt_is_a_clear_error(self):
        with mock.patch.dict(sys.modules, {'crypt': None}):
            with self.assertRaises(RuntimeError):
                bootinfo.root_password_edit('outra')


@unittest.skipUnless(shutil.which('bash') and shutil.which('sed'), 'precisa de bash e sed')
class BuildShSedTest(unittest.TestCase):
    """src/cic/build.sh usa sed -i num formato que funciona no sed do macOS (BSD) e no do Linux (GNU)."""

    def test_no_bsd_only_sed_left(self):
        self.assertNotIn("sed -i ''", open(BUILD_SH).read())

    def test_sedi_edits_in_place_without_leftovers(self):
        line = next(l for l in open(BUILD_SH) if l.startswith('sedi()'))
        d = tempfile.mkdtemp()
        try:
            f = os.path.join(d, 'meson.build')
            open(f, 'w').write("hw_arch += {'sh4': sh4_ss}\n")
            subprocess.run(['bash', '-c', line + '\nsedi "s|^hw_arch|x_arch|" "$1"', '_', f], check=True)
            self.assertEqual(open(f).read(), "x_arch += {'sh4': sh4_ss}\n")
            self.assertEqual(os.listdir(d), ['meson.build'])         # sem o .idemu-bak
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()
