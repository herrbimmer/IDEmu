import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'idemu', 'web')


def read(*p):
    with open(os.path.join(ROOT, *p), encoding='utf-8') as f:
        return f.read()


class RearCameraWiringTest(unittest.TestCase):
    """A câmera de ré roda no navegador; aqui só se confere que as peças estão ligadas entre si."""

    def test_script_is_loaded_after_tabs_and_before_run(self):
        html = read('idemu', 'web', 'index.html')
        order = [html.index('src="%s.js"' % n) for n in ('tabs', 'camera', 'run')]
        self.assertEqual(order, sorted(order))

    def test_run_view_has_tab_and_overlay(self):
        run = read('idemu', 'web', 'run.js')
        self.assertIn("['camera', 'Câmera de ré', 'camera']", run)
        self.assertIn('IDE.rvc.attach(dispWrap)', run)
        self.assertIn('detachRvc()', run)                      # a webcam é liberada ao sair da tela
        self.assertIn("t === 'camera'", run)                   # disponível também no iDrive 7/8

    def test_camera_uses_reverse_gear_and_never_uploads_frames(self):
        js = read('idemu', 'web', 'camera.js')
        self.assertIn('gear_position', js)
        self.assertIn('audio: false', js)
        self.assertNotRegex(js, r"post\('/api/(?!can/set)")    # nenhum quadro de vídeo vai ao servidor
        self.assertNotIn('WebSocket', js)

    def test_icon_and_i18n_check_cover_the_new_file(self):
        self.assertIn('camera:', read('idemu', 'web', 'util.js'))
        self.assertIn("'camera.js'", read('tools', 'i18n_check.py'))
        self.assertRegex(read('idemu', 'web', 'i18n.js'), r"\['Câmera de ré', 'Rear-view camera'\]")

    def test_electron_only_grants_video_to_own_origin(self):
        m = read('electron', 'main.js')
        self.assertIn("permission !== 'media'", m)
        self.assertRegex(m, r"every\(\(t\) => t === 'video'\)")


if __name__ == '__main__':
    unittest.main()
