"""iDrive Touch Controller (iDrive 5/6): the guest input commands Runtime.touchpad sends (events 41 and 42, src/shim/hook.c)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import runtime


class Rt(object):
    def __init__(self): self.sent = []
    def send_cmd(self, line): self.sent.append(line)


class TouchpadCommandsTest(unittest.TestCase):
    def test_one_finger(self):
        r = Rt(); runtime.Runtime.touchpad(r, 0.4, 0.4, True)
        self.assertEqual(len(r.sent), 1)
        self.assertEqual(r.sent[0].split()[:3], ['41', '1', str(204 | 204 << 16)])            # down, 0..511
        r = Rt(); runtime.Runtime.touchpad(r, 0.4, 0.6, True, move=True)
        self.assertEqual(r.sent[0].split()[:3], ['41', '2', str(204 | 307 << 16)])            # move
        r = Rt(); runtime.Runtime.touchpad(r, 1, 0, False)
        self.assertEqual(r.sent[0].split()[:3], ['41', '3', '511'])                           # up

    def test_clamped(self):
        r = Rt(); runtime.Runtime.touchpad(r, -0.5, 1.5, True)
        self.assertEqual(r.sent[0].split()[2], str(0 | 511 << 16))

    def test_two_fingers(self):
        r = Rt(); runtime.Runtime.touchpad(r, 0.2, 0.2, True, move=True, x2=0.8, y2=0.8)
        self.assertEqual(r.sent[0], '42 2 %d 0' % (409 | 409 << 16))                         # the second finger first
        self.assertEqual(r.sent[1].split()[:3], ['41', str(2 | 0x100), str(102 | 102 << 16)])


class CodedTest(unittest.TestCase):
    """The web UI shows the touchpad only when ZBE_TOUCH is coded (Runtime.status()['touchpad'])."""
    def test_zbe_touch(self):
        from idemu import codegen
        self.assertTrue(codegen.has_touch_controller({'coding': {}}))
        self.assertFalse(codegen.has_touch_controller({'coding': {'hu_variant': 'entrynav'}}))          # EntryNav: no touch
        self.assertFalse(codegen.has_touch_controller({'coding': {'extra': {'ZBE_TOUCH': 'nicht_aktiv'}}}))
        self.assertFalse(codegen.has_touch_controller({'coding': {'extra': {'ZBE_TOUCH': 0}}}))
        self.assertTrue(codegen.has_touch_controller({'coding': {'hu_variant': 'entrynav', 'extra': {'ZBE_TOUCH': 1}}}))

    def test_runtime_flag(self):
        class R(object): env = {'coding': {'extra': {'ZBE_TOUCH': 0}}}
        self.assertFalse(runtime.Runtime.has_touchpad(R()))
        class R2(object): env = {'coding': {}}
        self.assertTrue(runtime.Runtime.has_touchpad(R2()))
        class Other(object): env = {'coding': {}}; kind = 'mgu7'
        self.assertFalse(runtime.Runtime.has_touchpad(Other()))


if __name__ == '__main__':
    unittest.main()
