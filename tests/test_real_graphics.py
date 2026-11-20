"""real_graphics (docs/REAL_GRAPHICS.md): the flag changes nothing for other environments, the shim files follow the
environment's display, the view switch, and the host side of the HMI mirror."""
import os
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from idemu import builder, hmimirror_host, runtime  # noqa: E402


class LaunchTest(unittest.TestCase):
    def launch(self, **env):
        """Runs Runtime._launch with the processes and QMP replaced; returns (runtime, {name: (args, environment)})."""
        d = tempfile.mkdtemp(); self.addCleanup(lambda: __import__('shutil').rmtree(d, ignore_errors=True))
        rt = runtime.Runtime(os.path.join(d, 'env'), dict({'id': 't'}, **env), run_root=os.path.join(d, 'run'))
        os.makedirs(rt.run); open(os.path.join(rt.run, 'gl.sock'), 'w').close()
        calls = {}
        with mock.patch.object(rt, '_spawn', side_effect=lambda attr, args, **kw: calls.__setitem__(attr, (args, kw.get('env')))), \
                mock.patch.object(rt, '_log', return_value=None), mock.patch.object(runtime, 'Qmp'):
            rt._launch()
        return rt, calls

    def test_without_the_flag_nothing_changes(self):
        rt, calls = self.launch()
        args, env = calls['q']
        self.assertNotIn('IDEMU_DSS', env); self.assertNotIn('IDEMU_DSS_FRAME', env)
        self.assertNotIn('IDEMU_DSS', calls['gl'][1])
        self.assertFalse(any('memory-backend' in a or 'omap5ram' in a for a in args))
        self.assertEqual(args.count('-qmp'), 1)
        self.assertFalse(rt.real_graphics()); self.assertTrue(rt.fast_boot_enabled())

    def test_real_graphics_adds_the_dss_model_and_shared_ram(self):
        rt, calls = self.launch(real_graphics=True, fast_boot=True)
        args, env = calls['q']
        self.assertEqual(env['IDEMU_DSS'], '1')
        self.assertEqual(env['IDEMU_DSS_FRAME'], os.path.join(rt.run, 'dss.rgb'))
        self.assertIn('memory-backend-file,id=omap5ram,size=2048M,mem-path=%s,share=on' % os.path.join(rt.run, 'ram.bin'), args)
        self.assertIn('memory-backend=omap5ram', args)
        self.assertFalse(rt.fast_boot_enabled())        # always a cold boot

    def test_only_idrive_5_and_6(self):
        for kind in ('mgu7', 'mgu22', 'cic'):
            rt = runtime.Runtime('/nonexistent', {'id': 't', 'kind': kind, 'real_graphics': True}, run_root='/nonexistent')
            self.assertFalse(rt.real_graphics(), kind)


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(lambda: __import__('shutil').rmtree(self.d, ignore_errors=True))

    def rt(self, **env):
        r = runtime.Runtime(os.path.join(self.d, 'env'), dict({'id': 't'}, **env), run_root=os.path.join(self.d, 'run'))
        os.makedirs(r.run, exist_ok=True); return r

    def test_real_display_once_running_and_switchable(self):
        r = self.rt(real_graphics=True)
        self.assertEqual(r.view(), 'idemu')                        # boot progress follows the renderer
        r.state = 'running'
        self.assertEqual(r.view(), 'idemu'); self.assertEqual(r._frame_file(), r.frame_path)     # QEMU without the DSS model
        open(os.path.join(r.run, 'dss.rgb'), 'wb').close()
        self.assertEqual(r.view(), 'real')
        self.assertEqual(r._frame_file(), os.path.join(r.run, 'dss.rgb'))
        self.assertEqual(r.set_view('idemu'), 'idemu'); self.assertEqual(r._frame_file(), r.frame_path)
        self.assertEqual(r.set_view('bogus'), 'idemu')
        self.assertEqual(r.set_view('real'), 'real')

    def test_plain_environment_has_one_view(self):
        r = self.rt(); r.state = 'running'; open(os.path.join(r.run, 'dss.rgb'), 'wb').close()
        self.assertEqual(r.set_view('real'), 'idemu'); self.assertEqual(r._frame_file(), r.frame_path)


class ShimFilesTest(unittest.TestCase):
    def test_display_size(self):
        self.assertEqual(builder.realgfx_mode({}), (1440, 540))
        self.assertEqual(builder.realgfx_mode({'coding': {'display': '8_8_1280x480'}}), (1280, 480))
        self.assertEqual(builder.realgfx_mode({'coding': {'display': '6_5_800x480'}}), (800, 480))

    def test_files_follow_the_display(self):
        files = {n: (m, data) for n, m, data in builder.realgfx_files({'coding': {'display': '8_8_1280x480'}})}
        self.assertEqual(sorted(files), ['graphics.conf', 'hmimirror', 'mode.sh', 'start.sh'])
        conf = files['graphics.conf'][1].decode()
        self.assertIn('video-mode = 1280 x 480 @ 60', conf); self.assertNotIn('{', conf)
        self.assertIn('blit-config = sw', conf); self.assertNotIn('vivante', conf)
        self.assertIn(b'RG_W=1280 RG_H=480', files['mode.sh'][1])
        self.assertEqual(files['start.sh'][0], 0o100755); self.assertEqual(files['hmimirror'][0], 0o100755)
        elf = files['hmimirror'][1]
        self.assertEqual(elf[:4], b'\x7fELF'); self.assertEqual(struct.unpack_from('<H', elf, 18)[0], 40)     # ARM
        self.assertIn(b'/usr/lib/ldqnx.so.2', elf)                                                           # QNX


class MirrorHostTest(unittest.TestCase):
    def mirror(self, w, h, stride):
        d = tempfile.mkdtemp(); self.addCleanup(lambda: __import__('shutil').rmtree(d, ignore_errors=True))
        open(os.path.join(d, 'ram.bin'), 'wb').write(bytes(0x4000))
        rgb = bytes((x * 10 + y, 100 + x, 200 + y) [c] for y in range(h) for x in range(w) for c in range(3))
        fp = os.path.join(d, 'frame.rgb')
        open(fp, 'wb').write(struct.pack('<IIIII', 0x52464449, 7, w, h, 7).ljust(32, b'\0') + rgb)
        stop = threading.Event(); logs = []
        m = (w, h, stride, [(0, 0x80001000, stride * h)], 0x80000000)
        with mock.patch.object(hmimirror_host, '_read_map', return_value=m):
            t = threading.Thread(target=hmimirror_host.run, args=(d, fp, stop, logs.append)); t.start()
            for _ in range(200):
                if struct.unpack_from('<I', open(os.path.join(d, 'ram.bin'), 'rb').read(4))[0]: break
                stop.wait(0.01)
            stop.set(); t.join(5)
        ram = open(os.path.join(d, 'ram.bin'), 'rb').read()
        return ram, rgb

    def check(self, w, h, stride):
        ram, rgb = self.mirror(w, h, stride)
        self.assertEqual(struct.unpack_from('<I', ram, 0)[0], 1)              # the control counter was bumped once
        for y in range(h):
            for x in range(w):
                r, g, b = rgb[(y * w + x) * 3:(y * w + x) * 3 + 3]
                self.assertEqual(ram[0x1000 + y * stride + x * 4:0x1000 + y * stride + x * 4 + 4], bytes((b, g, r, 0xff)))

    def test_copies_bgra(self):
        self.check(4, 3, 16)

    def test_copies_rows_with_a_padded_stride(self):
        self.check(4, 3, 24)


if __name__ == '__main__':
    unittest.main()
