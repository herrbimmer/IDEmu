"""Handwriting on the iDrive Touch Controller (idemu/hwr.py): candidates, the CccsCharacterRecognition(2) messages, and the controller's
FktIDs / CccsTouchControl handling in idemu/most.py."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import hwr, most


class CandidatesTest(unittest.TestCase):
    def test_latin_case_and_lookalikes(self):
        self.assertEqual(hwr.candidates([('А', 100)]), [('A', 100), ('a', 90)])          # Cyrillic A -> Latin
        self.assertEqual(hwr.candidates([('0', 50)]), [('0', 50), ('O', 30), ('o', 20)])
        self.assertEqual(hwr.candidates([('s', 50)], 0x02), [('S', 40)])                  # upper case only
        self.assertEqual(hwr.candidates([('7', 80)], 0x06), [])                           # no digits wanted
        self.assertEqual(len(hwr.candidates([('B', 90), ('8', 70), ('R', 60)])), 4)

    def test_messages(self):
        self.assertEqual([b.hex() for b in hwr.messages([('M', 100), ('m', 90)], hwr.F_CHARREC2)], ['020064004d015a006d00'])
        self.assertEqual([b.hex() for b in hwr.messages([('0', 50), ('O', 30), ('o', 20)], hwr.F_CHARREC)],
                         ['0300320030011e004f', '030214006f00000000'])


class BridgeTest(unittest.TestCase):
    def bridge(self):
        class Link(object):
            def log(self, *a): pass
            def send(self, chan, frame): pass
        b = most.MostBridge(Link()); sent = []; b.send_most = sent.append
        return b, sent

    def test_fktids_answered(self):
        b, sent = self.bridge()
        b.on_most(most.MostMessage(0x100, 0x200, 0xE5, 1, 0, most.MostMessage.OP_GET))
        self.assertEqual([(m.fblock, m.inst, m.func, m.op, m.data) for m in sent], [(0xE5, 1, 0, most.MostMessage.OP_STATUS, b'\xff\xff\xff')])
        b.on_most(most.MostMessage(0x100, 0x200, 0xE5, 1, 0xC30, most.MostMessage.OP_SET, b'\x1d\x01\x05\x00'))
        self.assertEqual(len(sent), 1)                     # already told: not again

    def test_fktids_sent_unasked_after_restore(self):
        b, sent = self.bridge()
        b.on_most(most.MostMessage(0x100, 0x200, 0xE5, 1, 0xC30, most.MostMessage.OP_SET, b'\x1d\x01\x05\x00'))
        self.assertEqual([(m.func, m.op, m.data) for m in sent], [(0, most.MostMessage.OP_STATUS, b'\xff\xff\xff')])

    def test_touch_control_tracked(self):
        b, sent = self.bridge()
        h = hwr.Handwriting(b)
        self.assertFalse(h.active())
        b.on_most(most.MostMessage(0x100, 0x200, 0xE5, 1, 0xC41, most.MostMessage.OP_SET, bytes.fromhex('030f020000000001')))
        self.assertTrue(h.active())
        b.on_most(most.MostMessage(0x100, 0x200, 0xE5, 1, 0xC41, most.MostMessage.OP_SET, bytes.fromhex('0700ff000000bf01')))   # CarPlay: gestures
        self.assertFalse(h.active())


@unittest.skipUnless(os.path.isfile(hwr.HWR_BIN), 'bin/hwr not built (tools/hwr/build.sh)')
class RecogniseTest(unittest.TestCase):
    def test_letters(self):
        a = [[(0.2, 0.9), (0.5, 0.1), (0.8, 0.9)], [(0.33, 0.6), (0.67, 0.6)]]
        h = [[(0.25, 0.1), (0.25, 0.9)], [(0.75, 0.1), (0.75, 0.9)], [(0.25, 0.5), (0.75, 0.5)]]
        self.assertEqual(hwr.candidates(hwr.recognise(a))[0][0], 'A')
        self.assertEqual(hwr.candidates(hwr.recognise(h))[0][0], 'H')


if __name__ == '__main__':
    unittest.main()
