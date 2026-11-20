"""CIC (antigo "iDrive 4") e iDrive 7: nome, nível de funcionalidade e o console compartilhado que alimenta o SSH."""
import os, socket, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import catalog, cic, runtime


class NameTest(unittest.TestCase):
    def test_geracao_chama_cic(self):
        g = {x['id']: x for x in catalog.GENERATIONS}
        self.assertEqual(g['id4']['name'], 'CIC')            # o id 'id4' continua o mesmo: ambientes já salvos o usam
        self.assertNotIn('iDrive 4', ' '.join(x['name'] + x['sub'] for x in catalog.GENERATIONS))

    def test_mensagens_sem_idrive4(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ('idemu/cic.py', 'idemu/server.py', 'idemu/sysfiles.py', 'idemu/catalog.py', 'idemu/web/envtools.js', 'idemu/web/packages.js'):
            with open(os.path.join(root, rel), encoding='utf-8') as f: self.assertNotIn('iDrive 4', f.read(), rel)


class LevelTest(unittest.TestCase):
    def feat(self, gen, fid):
        return next(f for f in catalog.level_of(gen)['features'] if f['id'] == fid)['state']

    def test_ssh_funciona_no_cic_e_no_idrive7(self):
        self.assertEqual(self.feat('id4', 'ssh'), 'full')
        self.assertEqual(self.feat('id7', 'ssh'), 'full')
        self.assertEqual(self.feat('id8', 'ssh'), 'full')    # o shell da ttyAMA0 do guest vai para o SSH pelo mesmo ConsoleMux


class ConsoleMuxTest(unittest.TestCase):
    def test_entrada_vai_ao_guest_e_saida_vai_aos_clientes(self):
        with tempfile.TemporaryDirectory() as d:
            got = []; mux = runtime.ConsoleMux(os.path.join(d, 'shell.sock'), got.append); mux.start()
            c = socket.socket(socket.AF_UNIX)
            try:
                c.connect(os.path.join(d, 'shell.sock')); c.settimeout(2)
                c.sendall(b'ls\n')
                for _ in range(50):
                    if got: break
                    time.sleep(0.05)
                self.assertEqual(b''.join(got), b'ls\n')
                for _ in range(50):                           # o cliente só entra na lista depois do accept
                    if mux.clients: break
                    time.sleep(0.05)
                mux.feed(b'root# ')
                self.assertEqual(c.recv(100), b'root# ')
                self.assertEqual(''.join(mux.tail), 'root# ')
            finally:
                c.close(); mux.close()
            self.assertEqual(mux.clients, [])



class CicImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = cic.OUT, cic.find_pkg
        cic.OUT = self.tmp.name; self.pkg = os.path.join(self.tmp.name, 'swfl.bin'); open(self.pkg, 'wb').close()
        cic.find_pkg = lambda psdz=None: None

    def tearDown(self):
        cic.OUT, cic.find_pkg = self.old; self.tmp.cleanup()

    def write(self, **kw):
        import json
        with open(os.path.join(cic.OUT, 'build.json'), 'w') as f: json.dump(dict({'pkg': self.pkg}, **kw), f)

    def test_stale_quando_o_carimbo_muda_e_o_pacote_existe(self):
        self.write(); self.assertTrue(cic.image_stale())                        # build.json antigo, sem carimbo
        self.write(stamp=cic._stamp()); self.assertFalse(cic.image_stale())
        self.write(stamp='outro'); self.assertTrue(cic.image_stale())

    def test_sem_pacote_nao_tenta_refazer(self):
        self.write(pkg=os.path.join(self.tmp.name, 'sumiu.bin')); self.assertFalse(cic.image_stale())   # a PSdZData saiu do lugar e não há cópia
        cic.find_pkg = lambda psdz=None: self.pkg                              # ... mas há uma em ~/Downloads/System files/ID4
        self.write(pkg=os.path.join(self.tmp.name, 'sumiu.bin')); self.assertTrue(cic.image_stale())

    def test_patch_do_flexgps_e_idempotente(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('hmiinput', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'cic', 'hmiinput.py'))
        h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
        data = b'\x00' * 64 + h.FLEXGPS_OLD + b'\x11' * 64
        new = h.patch_flexgps(data)
        self.assertNotEqual(new, data); self.assertEqual(len(new), len(data)); self.assertIn(h.FLEXGPS_NEW, new)
        self.assertEqual(h.patch_flexgps(new), new)
        self.assertEqual(h.patch_flexgps(b'sem padrao'), b'sem padrao')


if __name__ == '__main__':
    unittest.main()
