"""CarPlay: each CarPlayControllerInput (0x24/0x70 0xCD3) and CarPlayTouchInput (0xCD5) the HMI sends is listed on the CarPlay
video (<ctl>/input.sock, "V k <text>", drawn by glhost) while "Show keystrokes" is on."""
import os, socket, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import most


class CarPlayKeysTest(unittest.TestCase):
    def test_text(self):
        t = most.MostBridge.carplay_key_text
        self.assertEqual(t(bytes([1, 0, 0, 0, 0, 0, 0, 0]), 1), '#1  01 00 00 00 00 00 00 00  rot +1')
        self.assertEqual(t(bytes([0x81, 0, 0, 0, 0, 0, 0, 0]), 2), '#2  81 00 00 00 00 00 00 00  rot -2')
        self.assertEqual(t(bytes([0, 1, 0, 0, 0, 0, 0, 1]), 3), '#3  00 01 00 00 00 00 00 01  press voice')
        self.assertEqual(t(bytes([0, 0, 1, 1, 0, 0, 1, 0]), 4), '#4  00 00 01 01 00 00 01 00  back up right')
        self.assertEqual(t(bytes(8), 5), '#5  00 00 00 00 00 00 00 00  released')
        self.assertEqual(t(b'\x01\x02', 6), '#6  01 02  (short: 2 bytes)')

    def test_touch_text(self):
        t = most.MostBridge.carplay_touch_text
        self.assertEqual(t(bytes.fromhex('000100c800641e00'), 1), '#1  touch 00 01 00c8 0064 1e 00  200,100 down')
        self.assertEqual(t(bytes.fromhex('000101dd01661e02'), 2), '#2  touch 00 01 01dd 0166 1e 02  477,358 up')
        self.assertEqual(t(bytes.fromhex('000100c8'), 3), '#3  touch 00 01  (short)')
        self.assertEqual(t(b'\x00', 4), '#4  touch 00  (short)')

    def test_listed_on_video(self):
        class Link(object):
            def log(self, *a): pass
            def send(self, chan, frame): pass
        with tempfile.TemporaryDirectory() as ctl:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); s.bind(os.path.join(ctl, 'input.sock')); s.settimeout(2)
            b = most.MostBridge(Link()); b.send_most = lambda m: None; b.ctl = ctl; b.carplay_keys = True   # "Show keystrokes" on
            for d in (bytes([0, 0, 1, 0, 0, 0, 0, 0]), bytes(8)):
                b.on_most(most.MostMessage(0x100, 0x200, 0x24, 0x70, 0xcd3, most.MostMessage.OP_SET, d))
            b.on_most(most.MostMessage(0x100, 0x200, 0x24, 0x70, 0xcd1, most.MostMessage.OP_SET, b'\x01'))   # ChangeModes: not a key
            b.on_most(most.MostMessage(0x100, 0x200, 0x24, 0x70, 0xcd5, most.MostMessage.OP_SET, bytes.fromhex('000100c800641e02')))
            self.assertEqual(s.recv(200), b'V k #1  00 00 01 00 00 00 00 00  back')
            self.assertEqual(s.recv(200), b'V k #2  00 00 00 00 00 00 00 00  released')
            self.assertEqual(s.recv(200), b'V k #3  touch 00 01 00c8 0064 1e 02  200,100 up')
            s.setblocking(False)
            self.assertRaises(BlockingIOError, s.recv, 200)
            s.close()

if __name__ == '__main__':
    unittest.main()
