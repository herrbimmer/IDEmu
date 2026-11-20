"""Cluster e HUD virtuais (idemu/cluster.py), nível de funcionalidade por versão (catalog.py) e pasta da VM (server.App)."""
import json, os, shutil, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import catalog, cluster, gps, server


class FakeCan(object):
    def __init__(self, **v): self.v = v
    def get_signal(self, n):
        if n not in self.v: raise KeyError(n)
        return self.v[n]


class FakeBridge(object):
    def __init__(self, seen): self.seen = seen


class NextTurnTest(unittest.TestCase):
    def route(self, pts): return gps.Route('t', pts)

    def test_right_turn_after_straight(self):
        r = self.route([(-23.5, -46.6), (-23.5, -46.59), (-23.509, -46.59)])         # leste, depois sul
        t = cluster.next_turn(r, 0.0)
        self.assertEqual(t['dir'], 'right'); self.assertAlmostEqual(t['dist_m'], 1020, delta=60); self.assertAlmostEqual(t['angle'], 90, delta=15)

    def test_left_turn(self):
        t = cluster.next_turn(self.route([(-23.5, -46.6), (-23.5, -46.59), (-23.491, -46.59)]), 0.0)    # leste, depois norte
        self.assertEqual(t['dir'], 'left')

    def test_straight_route_has_no_turn(self):
        self.assertIsNone(cluster.next_turn(self.route([(-23.5, -46.6), (-23.5, -46.58)]), 0.0))

    def test_u_turn(self):
        t = cluster.next_turn(self.route([(-23.5, -46.6), (-23.5, -46.59), (-23.5, -46.6001)]), 0.0)
        self.assertEqual(t['dir'], 'uturn')

    def test_distance_shrinks_and_ends(self):
        r = self.route([(-23.5, -46.6), (-23.5, -46.59), (-23.509, -46.59)])
        a, b = cluster.next_turn(r, 0.0), cluster.next_turn(r, 500.0)
        self.assertLess(b['dist_m'], a['dist_m'])
        self.assertIsNone(cluster.next_turn(r, r.length_m - 10))
        self.assertIsNone(cluster.next_turn(None, 0.0))


class SnapshotTest(unittest.TestCase):
    def test_warnings(self):
        w = dict(cluster.warnings({'vehicle_speed': 50, 'seatbelt_driver': 0, 'door_driver': 1, 'fuel_level': 3, 'tire_pressure_fl': 1.2, 'headlight_low': 1, 'coolant_temp': 120}))
        self.assertEqual(w['belt_driver'], 'red'); self.assertEqual(w['door'], 'red'); self.assertEqual(w['fuel_low'], 'amber'); self.assertEqual(w['tire_low'], 'amber')
        self.assertEqual(w['coolant_hot'], 'red'); self.assertEqual(w['low_beam'], 'info')
        self.assertEqual(cluster.warnings({'vehicle_speed': 0, 'seatbelt_driver': 1, 'terminal_state': 69, 'fuel_level': 31, 'coolant_temp': 90}), [])

    def test_snapshot_values_and_range(self):
        c = FakeCan(vehicle_speed=88.0, fuel_level=31.0, fuel_consumption=10.0, gear_position=3.0)
        d = cluster.snapshot(c, None, None)
        self.assertEqual(d['signals']['vehicle_speed'], 88.0); self.assertEqual(d['fuel_pct'], 50.0); self.assertEqual(d['range_km'], 310)
        self.assertIsNone(d['gps']); self.assertEqual(d['hu'], [])

    def test_snapshot_with_gps_route(self):
        g = gps.GpsSim(); g.load_route('t', points=[(-23.5, -46.6), (-23.5, -46.59), (-23.509, -46.59)], speed_kmh=40)
        d = cluster.snapshot(FakeCan(vehicle_speed=40.0), g, None)
        self.assertEqual(d['gps']['turn']['dir'], 'right'); self.assertGreater(d['gps']['remaining_m'], 1000)

    def test_hu_messages_only_kombi_and_hud(self):
        now = time.time()
        seen = {(0xE0, 0, 0x200): {'op': 0, 'data': b'\x01\x02', 't': now - 5, 'n': 3}, (0xE1, 0, 0x410): {'op': 2, 'data': b'\xff', 't': now - 1, 'n': 1}, (0xE5, 1, 0xc30): {'op': 0, 'data': b'\x00', 't': now, 'n': 9}}
        m = cluster.hu_messages(seen, now)
        self.assertEqual([(x['fkt'], x['n'], x['hex']) for x in m], [(0x410, 1, 'ff'), (0x200, 3, '0102')])
        self.assertEqual(m[1]['name'], 'CNewCCMessage')


class LevelTest(unittest.TestCase):
    def test_every_generation_has_a_level(self):
        for g in catalog.GENERATIONS:
            lv = g['level']
            self.assertTrue(0 <= lv['pct'] <= 100); self.assertEqual(len(lv['features']), len(catalog.FEATURES))
            self.assertTrue(all(f['state'] in ('full', 'half', 'none') for f in lv['features']))
            pts = sum({'full': 1, 'half': .5, 'none': 0}[f['state']] for f in lv['features'])
            self.assertEqual(lv['pct'], int(round(100 * pts / len(catalog.FEATURES))))

    def test_order_and_names(self):
        pct = {g['id']: g['level']['pct'] for g in catalog.GENERATIONS}
        self.assertGreater(pct['id6'], pct['id5']); self.assertGreater(pct['id6'], pct['id8']); self.assertGreater(pct['id8'], pct['id7'])
        self.assertEqual(catalog.level_of('id6')['name'], 'Alto'); self.assertEqual(catalog.level_of('id7')['name'], 'Baixo')
        self.assertIn('level', catalog.build_catalog(None)['generations'][0])


class VmHomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.old = server.ENVS
        server.ENVS = os.path.join(self.tmp, 'environments'); os.makedirs(server.ENVS)
        self.disk = os.path.join(self.tmp, 'disco externo'); os.makedirs(self.disk)
        self.app = server.App()
        self.body = {'name': 'Meu carro', 'series': 'F020', 'chassis': 'F30', 'brand': 'bmw', 'coding': {}, 'swfl': {}}
        for r in ('os', 'brand', 'hmi'):
            p = os.path.join(self.tmp, 'swfl_%s.bin' % r); open(p, 'w').close(); self.body['swfl'][r] = p
    def tearDown(self): server.ENVS = self.old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_folder(self):
        e = self.app.create(self.body)
        self.assertNotIn('home', e); self.assertFalse(os.path.islink(self.app.env_dir(e['id'])))

    def test_chosen_folder_link_duplicate_delete(self):
        e = self.app.create(dict(self.body, home=self.disk))
        d = self.app.env_dir(e['id']); real = os.path.join(os.path.realpath(self.disk), e['id'])
        self.assertTrue(os.path.islink(d)); self.assertEqual(os.path.realpath(d), real); self.assertEqual(e['home'], os.path.realpath(self.disk))
        self.assertTrue(os.path.isfile(os.path.join(real, 'env.json')))
        c = self.app.duplicate(e['id'], 'Outro carro')
        self.assertEqual(c['home'], e['home']); self.assertTrue(os.path.isdir(os.path.join(real, '..', c['id'])))
        self.assertEqual(sorted(x['id'] for x in self.app.list_envs()), sorted([e['id'], c['id']]))
        self.app.delete(e['id']); self.app.delete(c['id'])
        self.assertEqual(os.listdir(self.disk), []); self.assertEqual(os.listdir(server.ENVS), [])
        self.assertTrue(os.path.isdir(self.disk))        # a pasta escolhida em si nunca é apagada

    def test_same_name_gets_a_free_id_and_keeps_existing_files(self):
        os.makedirs(os.path.join(self.disk, 'meu-carro')); open(os.path.join(self.disk, 'meu-carro', 'meu.txt'), 'w').close()
        e = self.app.create(dict(self.body, home=self.disk))
        self.assertEqual(e['id'], 'meu-carro-2'); self.assertTrue(os.path.isfile(os.path.join(self.disk, 'meu-carro', 'meu.txt')))
        self.app.delete(e['id']); self.assertTrue(os.path.isfile(os.path.join(self.disk, 'meu-carro', 'meu.txt')))

    def test_invalid_folders(self):
        with self.assertRaises(server.ApiError): self.app.create(dict(self.body, home=os.path.join(self.tmp, 'nao-existe')))
        ro = os.path.join(self.tmp, 'somente-leitura'); os.makedirs(ro); os.chmod(ro, 0o500)
        try:
            if os.access(ro, os.W_OK): self.skipTest('rodando como root')
            with self.assertRaises(server.ApiError): self.app.create(dict(self.body, home=ro))
        finally: os.chmod(ro, 0o700)
        self.assertEqual(os.listdir(server.ENVS), [])

    def test_default_folder_given_explicitly_is_not_linked(self):
        e = self.app.create(dict(self.body, home=server.ENVS))
        self.assertNotIn('home', e); self.assertFalse(os.path.islink(self.app.env_dir(e['id'])))

    def test_fs_space(self):
        sp = server.fs_space(self.disk)
        self.assertTrue(sp['writable']); self.assertGreater(sp['free'], 0); self.assertFalse(sp['default']); self.assertTrue(server.fs_space(server.ENVS)['default'])


if __name__ == '__main__':
    unittest.main()
