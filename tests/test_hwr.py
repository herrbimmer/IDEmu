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


class NoRecognizerTest(unittest.TestCase):
    """Where bin/hwr cannot be built (no macOS Vision): nothing is entered unless IDEMU_HWR_FALLBACK names a placeholder."""
    def setUp(self):
        from unittest import mock
        self.patches = [mock.patch.object(hwr, 'HWR_BIN', '/nonexistent/hwr'), mock.patch.object(hwr.sys, 'platform', 'linux'),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for p in self.patches: p.start()
        os.environ.pop(hwr.FALLBACK_ENV, None)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def bridge(self, classes=0x0F):
        class B(object):
            ccs_touch_control = bytes([3, classes, 2, 0, 0, 0, 0, 1])
            subs = {(0xE5, 1): {hwr.F_CHARREC2: 0x100}}
            def __init__(self): self.sent = []
            def publish(self, fblock, fkt, data, inst=1): self.sent.append((fblock, fkt, data, inst))
        return B()

    def write(self, b):
        logs = []; h = hwr.Handwriting(b, logs.append)
        for st, x, y in ((1, .3, .2), (2, .5, .8), (3, .7, .2)): h.touch(x, y, st)
        h.timer.cancel(); h._done()
        return logs

    def test_not_built_off_macos(self):
        from unittest import mock
        with mock.patch.object(hwr.subprocess, 'run') as run:
            self.assertIsNone(hwr.ensure_bin())
            run.assert_not_called()

    def test_nothing_sent_without_fallback(self):
        b = self.bridge(); logs = self.write(b)
        self.assertEqual(b.sent, [])
        self.assertIn('no recognizer', logs[-1])

    def test_placeholder(self):
        os.environ[hwr.FALLBACK_ENV] = 'A'
        b = self.bridge(); logs = self.write(b)
        self.assertEqual([(f, k, d.hex()) for f, k, d, _ in b.sent], [(0xE5, hwr.F_CHARREC2, '01006400410000000000')])
        self.assertIn('placeholder', logs[-1])

    def test_placeholder_class_not_wanted(self):
        os.environ[hwr.FALLBACK_ENV] = 'A'
        b = self.bridge(classes=0x01); self.write(b)          # digits only
        self.assertEqual(b.sent, [])


class AutoBuildTest(unittest.TestCase):
    def test_builds_once_when_missing(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, 'hwr')
            def run(cmd, **kw):
                open(exe, 'w').close()
                return mock.Mock(stdout=b'built bin/hwr\n', stderr=b'', returncode=0)
            with mock.patch.object(hwr, 'HWR_BIN', exe), mock.patch.object(hwr.sys, 'platform', 'darwin'), \
                 mock.patch.object(hwr, '_build_tried', False), mock.patch.object(hwr.subprocess, 'run', side_effect=run) as r:
                logs = []
                self.assertEqual(hwr.ensure_bin(logs.append), exe)
                self.assertEqual(r.call_args[0][0], ['zsh', hwr.HWR_BUILD])
                self.assertEqual(logs, ['handwriting: built bin/hwr'])
                os.utime(exe, (0, 0))                              # older than hwr.m: stale, but rebuilt only once per process
                self.assertEqual(hwr.ensure_bin(), exe)
                self.assertEqual(r.call_count, 1)


@unittest.skipUnless(os.path.isfile(hwr.HWR_BIN), 'bin/hwr not built (tools/hwr/build.sh)')
class RecogniseTest(unittest.TestCase):
    def test_letters(self):
        a = [[(0.2, 0.9), (0.5, 0.1), (0.8, 0.9)], [(0.33, 0.6), (0.67, 0.6)]]
        h = [[(0.25, 0.1), (0.25, 0.9)], [(0.75, 0.1), (0.75, 0.9)], [(0.25, 0.5), (0.75, 0.5)]]
        self.assertEqual(hwr.candidates(hwr.recognise(a))[0][0], 'A')
        self.assertEqual(hwr.candidates(hwr.recognise(h))[0][0], 'H')


if __name__ == '__main__':
    unittest.main()
