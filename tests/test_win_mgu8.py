"""iDrive 8 no Windows: lógica Python do port (ANGLE, aceleração, RAM compartilhada, console). Usa mocks de ipc.IS_WIN/mgu.IS_WIN: passa em qualquer sistema."""
import mmap, os, socket, struct, sys, tempfile, threading, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import mgu

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fake_pe(path, machine):
    """Arquivo mínimo com cabeçalho PE (MZ + e_lfanew + 'PE\\0\\0' + Machine)."""
    h = bytearray(64); h[0:2] = b'MZ'; struct.pack_into('<I', h, 0x3c, 64)
    with open(path, 'wb') as f:
        f.write(bytes(h) + b'PE\0\0' + struct.pack('<H', machine) + b'\0' * 32)


class PeTest(unittest.TestCase):
    def test_machine(self):
        with tempfile.TemporaryDirectory() as t:
            fake_pe(t + '/a.dll', 0x8664); fake_pe(t + '/b.dll', 0xAA64)
            open(t + '/c.dll', 'wb').write(b'nao e PE')
            self.assertEqual(mgu._pe_machine(t + '/a.dll'), 0x8664)
            self.assertEqual(mgu._pe_machine(t + '/b.dll'), 0xAA64)
            self.assertIsNone(mgu._pe_machine(t + '/c.dll'))
            self.assertIsNone(mgu._pe_machine(t + '/nao-existe.dll'))


class AngleWinTest(unittest.TestCase):
    def _app(self, root, ver, machine):
        d = os.path.join(root, 'Microsoft', 'Edge', 'Application', ver); os.makedirs(d)
        fake_pe(os.path.join(d, 'libEGL.dll'), machine); fake_pe(os.path.join(d, 'libGLESv2.dll'), machine)
        return d

    def test_newest_version_wins_and_only_x64(self):
        with tempfile.TemporaryDirectory() as t:
            old = self._app(t, '99.0.1.2', 0x8664); new = self._app(t, '120.0.2210.91', 0x8664)
            arm = self._app(t, '130.0.0.1', 0xAA64)               # ARM64: o mguhost.exe é x86-64, não serve
            env = {'ProgramFiles': t, 'ProgramFiles(x86)': '', 'ProgramW6432': '', 'LOCALAPPDATA': ''}
            with mock.patch.dict(os.environ, env), mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu.runtime, 'BIN', os.path.join(t, 'bin')), \
                    mock.patch.object(mgu, 'mguhost_path', side_effect=RuntimeError('sem exe')):
                os.environ.pop('IDEMU_ANGLE', None)
                self.assertEqual(os.path.normpath(mgu.find_angle()), os.path.normpath(new))
                dirs = mgu._angle_dirs_win()
                self.assertLess(dirs.index(arm), dirs.index(new))   # a ordem é pela versão; a validação de arquitetura é do find_angle
                self.assertLess(dirs.index(new), dirs.index(old))

    def test_missing_raises_with_hint(self):
        with tempfile.TemporaryDirectory() as t:
            env = {'ProgramFiles': t, 'ProgramFiles(x86)': '', 'ProgramW6432': '', 'LOCALAPPDATA': ''}
            with mock.patch.dict(os.environ, env), mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu.runtime, 'BIN', os.path.join(t, 'bin')), \
                    mock.patch.object(mgu, 'mguhost_path', side_effect=RuntimeError('sem exe')):
                os.environ.pop('IDEMU_ANGLE', None)
                with self.assertRaises(RuntimeError) as c:
                    mgu.find_angle()
                self.assertIn('IDEMU_ANGLE', str(c.exception))


class AccelTest(unittest.TestCase):
    def _clean(self):
        for k in ('IDEMU_MGU_ACCEL', 'IDEMU_MGU_CPU'): os.environ.pop(k, None)

    def test_mac_is_hvf(self):
        with mock.patch.object(mgu, 'IS_WIN', False):
            self.assertEqual(mgu.accel_args(), (['-accel', 'hvf', '-cpu', 'host'], 'hvf'))

    def test_x86_windows_is_tcg(self):
        with mock.patch.dict(os.environ), mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu, '_host_arm64', return_value=False):
            self._clean()
            a, kind = mgu.accel_args()
            self.assertEqual(kind, 'tcg'); self.assertIn('tcg,thread=multi', a); self.assertEqual(a[a.index('-cpu') + 1], 'cortex-a76')

    def test_arm64_windows_uses_whpx_only_if_qemu_has_it(self):
        with mock.patch.dict(os.environ), mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu, '_host_arm64', return_value=True):
            self._clean()
            with mock.patch.object(mgu, '_qemu_accels', return_value='Accelerators supported in QEMU binary:\ntcg\nwhpx\n'):
                self.assertEqual(mgu.accel_args()[1], 'whpx')
            with mock.patch.object(mgu, '_qemu_accels', return_value='Accelerators supported in QEMU binary:\ntcg\n'):
                self.assertEqual(mgu.accel_args()[1], 'tcg')

    def test_env_cpu_override(self):
        with mock.patch.dict(os.environ, {'IDEMU_MGU_CPU': 'max'}), mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu, '_host_arm64', return_value=False):
            os.environ.pop('IDEMU_MGU_ACCEL', None)
            a, _ = mgu.accel_args()
            self.assertEqual(a[a.index('-cpu') + 1], 'max')


class FakeMap:
    """No lugar do mmap de 12 GiB: guarda só o que foi escrito."""
    def __init__(self, fileno, length, tagname=None):
        self.length, self.tag, self.w, self.closed = length, tagname, [], False
    def __setitem__(self, k, v): self.w.append((k.start, k.start + len(v)))
    def close(self): self.closed = True


class PrepareRamWinTest(unittest.TestCase):
    def test_windows_section_and_dtb(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(t + '/guest')
            for f in mgu.GUEST_FILES: open(t + '/guest/' + f, 'wb').write(b'x')
            open(t + '/base.cpio', 'wb').write(b'c' * 1000)
            backing = mock.Mock()

            def fake_ram(name, folder):
                self.assertEqual(folder, t)
                return FakeMap(None, mgu.MB << 20, name), backing

            with mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu, 'OUT', t), mock.patch.object(mgu, '_windows_ram', fake_ram):
                m, name, storage = mgu._prepare_ram(t + '/boot.dtb')
            self.assertIs(storage, backing)
            backing.close.assert_not_called()
            self.assertFalse(m.closed)
            self.assertEqual(m.length, mgu.MB << 20)
            self.assertEqual(m.tag, name)
            self.assertRegex(name, r'^idemu_ram_[0-9a-f]{32}$')
            self.assertEqual(m.w[0][0], mgu.INITRD_AT - mgu.GUEST_BASE)
            d = open(t + '/boot.dtb', 'rb').read()
            self.assertNotIn(struct.pack('>II', 0xdeadbeef, 0xfeedf00d), d)       # o marcador do fim do initramfs foi trocado

    def test_mapping_failure_message(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(t + '/guest')
            for f in mgu.GUEST_FILES: open(t + '/guest/' + f, 'wb').write(b'x')
            open(t + '/base.cpio', 'wb').write(b'c')
            def boom(*a, **k): raise OSError('not enough space for the mapping')
            with mock.patch.object(mgu, 'IS_WIN', True), mock.patch.object(mgu, 'OUT', t), mock.patch.object(mgu, '_windows_ram', boom):
                with self.assertRaises(RuntimeError) as c:
                    mgu._prepare_ram(t + '/boot.dtb')
                self.assertIn('not enough space for the mapping', str(c.exception))


    @unittest.skipUnless(os.name == 'nt', 'Windows named section')
    def test_file_backed_section_lifetime(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mgu, 'MB', 1):
            tag = 'idemu-test-' + os.path.basename(folder)
            mapping, storage = mgu._windows_ram(tag, folder)
            try:
                with mmap.mmap(-1, 1 << 20, tagname=tag) as consumer:
                    mapping[:4] = b'IDEM'
                    mapping.close()
                    self.assertEqual(consumer[:4], b'IDEM')
                    self.assertFalse(storage.closed)
            finally:
                mapping.close()
                storage.close()
            self.assertEqual(os.listdir(folder), [])


class ConsoleWinTest(unittest.TestCase):
    def test_con_write_goes_to_socket(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(mgu, 'IS_WIN', True):
            rt = mgu.MguRuntime(t, {'id': 'teste-mgu'})
            a, b = socket.socketpair()
            try:
                rt._ser = a
                rt._con_write(b'ls\n'); rt.guest('id')
                b.settimeout(2); got = b''
                while len(got) < 6: got += b.recv(64)
                self.assertEqual(got, b'ls\nid\n')
                rt._ser = None
                rt._con_write(b'x')                                              # sem socket: não levanta
            finally:
                a.close(); b.close()

    def test_pump_feeds_log_and_mux(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(mgu, 'IS_WIN', True):
            rt = mgu.MguRuntime(t, {'id': 'teste-mgu'})
            fed = []
            class Mux:
                def feed(self, d): fed.append(d)
            rt.mux = Mux()
            a, b = socket.socketpair()
            lf = open(t + '/console.log', 'wb')
            th = threading.Thread(target=rt._pump_console, args=(a, lf)); th.start()
            b.sendall(b'IDEMU-HMI-START\n'); b.close()
            th.join(5); a.close()
            self.assertFalse(th.is_alive())
            self.assertEqual(b''.join(fed), b'IDEMU-HMI-START\n')
            self.assertEqual(open(t + '/console.log', 'rb').read(), b'IDEMU-HMI-START\n')


class SourceConsistencyTest(unittest.TestCase):
    """O protocolo guest/host manda 8 bytes: no host Windows (LLP64) o gerador e o cabeçalho do canal não podem usar `unsigned long`."""
    def test_generated_host_uses_64bit_reply(self):
        d = os.path.join(HERE, 'src', 'mgu22')
        inc = open(os.path.join(d, 'gen_host.inc'), encoding='utf-8').read()
        self.assertNotIn('unsigned long r =', inc)
        self.assertIn('unsigned long long r = (unsigned long long)(long long)', inc)
        self.assertIn('unsigned long long r = (unsigned long long)(long long)', open(os.path.join(d, 'gen.py'), encoding='utf-8').read())

    def test_chan_header_is_64bit_on_windows(self):
        t = open(os.path.join(HERE, 'src', 'mgu22', 'chan.h'), encoding='utf-8').read()
        self.assertIn('typedef unsigned long long ch_ul;', t)
        self.assertNotIn('unsigned long nonce', t)


if __name__ == '__main__':
    unittest.main()
