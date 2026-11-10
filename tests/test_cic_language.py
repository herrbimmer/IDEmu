import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import catalog, cic, server         # noqa: E402

# Set de HumanMachineInterface.CurrentLanguage (FBlock 0x10, inst 1, FktID 0x200) = 2 (inglês), vindo do ZGW (0x0102)
SET_EN = '000d0200010210010200000102'


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class LanguageCodeTest(unittest.TestCase):
    def test_measured_codes(self):
        self.assertEqual(cic.language_code('de_DE'), 1)
        self.assertEqual(cic.language_code('en_GB'), 2)
        self.assertEqual(cic.language_code('fr_FR'), 6)
        self.assertEqual(cic.language_code('sv_SE'), 23)

    def test_fallbacks(self):
        self.assertEqual(cic.language_code('en_US'), 2)                 # o banco de textos da ECE não tem inglês EUA
        self.assertEqual(cic.language_code('pt_BR'), cic.LANGUAGES['pt_PT'])
        self.assertEqual(cic.language_code('ja_JP'), 2)                 # idioma que o CIC não tem: inglês, como o HMI
        self.assertEqual(cic.language_code(None), 2)

    def test_codes_are_distinct_bytes(self):
        codes = list(cic.LANGUAGES.values())
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(0 < c < 256 for c in codes))


class VirtualZBELanguageTest(unittest.TestCase):
    """O idioma vai para o HMI quando ele configura o controlador (RotaryEncoderConfig.Set), pelo mesmo canal MTP."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir='/tmp')                        # caminho curto: sockets Unix têm limite de tamanho
        self.sent = []
        self.zbe = cic.VirtualZBE(self.tmp, self.sent.append)

    def tearDown(self):
        self.zbe.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hmi_configures_controller(self):
        # telegrama do HMI ao FBlock 0xE5: RotaryEncoderConfig (0xC30) Set com contador 0x07
        tel = bytes([0, 21, 2, 0, 0x01, 0x02, 0xe5, 0x01, 0x0c, 0x30, 0x00, 0x01, 0x1d, 0x01, 0x07, 0, 0, 0, 0x7f, 0xff, 0x1e])
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.sendto(('x ' + tel.hex()).encode(), self.zbe.out)
        s.close()

    def test_set_language_telegram(self):
        self.zbe.set_language(2)
        self.assertEqual(self.sent, ['t ' + SET_EN])

    def test_language_sent_once_when_configured(self):
        self.zbe.language = 2
        self.hmi_configures_controller()
        self.assertTrue(wait_for(lambda: self.zbe.configured))
        self.assertTrue(wait_for(lambda: ('t ' + SET_EN) in self.sent))
        self.hmi_configures_controller()                                # nova configuração (ex.: HMI reiniciado): sem repetir
        time.sleep(0.3)
        self.assertEqual(self.sent.count('t ' + SET_EN), 1)

    def test_no_language_no_set(self):
        self.hmi_configures_controller()
        self.assertTrue(wait_for(lambda: self.zbe.configured))
        time.sleep(0.2)
        self.assertFalse(any(t.startswith('t 000d0200010210') for t in self.sent))


class CreateCicEnvLanguageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.old = server.ENVS
        server.ENVS = os.path.join(self.tmp, 'environments'); os.makedirs(server.ENVS)
        self.app = server.App()
        self.p = mock.patch.object(catalog, 'packages_ok', return_value=True); self.p.start()

    def tearDown(self):
        self.p.stop(); server.ENVS = self.old; shutil.rmtree(self.tmp, ignore_errors=True)

    def lang(self, coding):
        return self.app.create({'kind': 'cic', 'name': 'CIC', 'coding': coding})['coding']['language']

    def test_language_from_wizard(self):
        self.assertEqual(self.lang({'language': 'en_GB'}), 'en_GB')
        self.assertEqual(self.lang({'language': 'pt_BR'}), 'pt_BR')    # guardado como veio; o código usa o fallback

    def test_default_stays_german(self):
        self.assertEqual(self.lang(None), 'de_DE')                      # ambientes criados pela API sem idioma: como antes

    def test_unknown_language_becomes_english(self):
        self.assertEqual(self.lang({'language': 'xx_YY'}), 'en_GB')


if __name__ == '__main__':
    unittest.main()
