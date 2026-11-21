"""iDrive 5/6: o servidor refaz o shim.img de um ambiente quando as bibliotecas do guest (idemu/shim/lib) ou os scripts de boot são mais novos que ele."""
import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import server
from idemu import builder
import json
from pathlib import Path
from unittest.mock import Mock, patch


class ShimStaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = server.ENVS
        server.ENVS = os.path.join(self.tmp.name, 'environments')
        self.img = os.path.join(server.ENVS, 'nbt', 'images'); os.makedirs(self.img)
        self.app = server.App()
        here = os.path.dirname(os.path.abspath(server.__file__))
        self.newest = max(os.path.getmtime(os.path.join(here, 'shim', 'lib', n)) for n in os.listdir(os.path.join(here, 'shim', 'lib')))

    def tearDown(self):
        server.ENVS = self.old; self.tmp.cleanup()

    def test_sem_shim_nao_refaz(self):
        self.assertFalse(self.app._shim_stale('nbt'))          # ambiente ainda não compilado: quem gera o shim é a compilação

    def test_shim_mais_velho_que_as_bibliotecas(self):
        p = os.path.join(self.img, 'shim.img'); open(p, 'wb').write(b'x')
        os.utime(p, (self.newest - 60, self.newest - 60))
        self.assertTrue(self.app._shim_stale('nbt'))

    def test_shim_de_32mb_e_refeito(self):
        p = os.path.join(self.img, 'shim.img')
        with open(p, 'wb') as f: f.truncate(32 << 20)                     # layout antigo (0x7e000000, sob o buffer da ponte GL)
        t = time.time() + 60; os.utime(p, (t, t))
        self.assertTrue(self.app._shim_stale('nbt'))

    def test_shim_em_dia(self):
        p = os.path.join(self.img, 'shim.img'); open(p, 'wb').write(b'x')
        t = time.time() + 60; os.utime(p, (t, t))
        self.assertFalse(self.app._shim_stale('nbt'))


class ShimRefreshTest(unittest.TestCase):
    version = "007_001_016"
    shim_profile = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {"id": "test-env", "coding": {}}
        if self.shim_profile:
            self.env["shim_profile"] = self.shim_profile
        self.app = server.App.__new__(server.App)
        self.app.rt = None
        self.app.flashes = {}
        self.app.env_dir = Mock(return_value=str(self.root))
        self.app.load_env = Mock(side_effect=lambda _: dict(self.env))
        self.app.build_info = Mock(return_value={"state": "ready"})
        self.app._extract_cfg = Mock()
        self.profile = json.loads((Path(builder.HERE) / ("data/firmwares/nbtevo-" + self.version + ".json")).read_text())
        self.manifest = {"hmi_sha256": self.profile["hmi_sha256"],
                         "shim_library_sha256": self.profile["library_sha256"]}
        (self.root / "build.json").write_text(json.dumps(self.manifest))

    def test_refresh_preserves_the_firmware_identity(self):
        with patch.object(builder, "build_shim") as build:
            self.app._rebuild_shim("test-env", self.env)
        build.assert_called_once_with(self.env, str(self.root / "work/os"), str(self.root / "images/shim.img"),
                                      hmi_sha=self.manifest["hmi_sha256"],
                                      library_hashes=self.manifest["shim_library_sha256"])
        self.assertFalse((self.root / "work").exists())
        selected = builder.shim_firmware(self.env, self.manifest["hmi_sha256"],
                                         self.manifest["shim_library_sha256"])
        self.assertEqual(selected, self.profile)

    def test_coding_flash_preserves_the_firmware_identity(self):
        with patch.object(server.coding, "apply_changes", return_value=[]), \
                patch.object(server.codegen, "build_table", return_value=(b"", 0, [])), \
                patch.object(server.codegen, "profile_for", return_value={}), \
                patch.object(server.coding, "backup", return_value="backup"), \
                patch.object(self.app, "save_env"), \
                patch.object(builder, "build_shim") as build, \
                patch.object(server.threading, "Thread") as thread:
            self.app._flash("test-env")
            thread.call_args.kwargs["target"]()
        self.assertEqual(self.app.flashes["test-env"]["state"], "done")
        build.assert_called_once_with(self.env, str(self.root / "work/os"), str(self.root / "images/shim.img"),
                                      hmi_sha=self.manifest["hmi_sha256"],
                                      library_hashes=self.manifest["shim_library_sha256"])

    def test_invalid_identity_cannot_mutate_or_stop_a_running_environment(self):
        self.env["coding"] = {"extra": {"existing": 1}}
        self.app.rt = Mock(id="test-env", state="running")
        snapshot = self.root / "snapshot" / "keep"
        snapshot.parent.mkdir()
        snapshot.write_text("existing snapshot")
        bad_manifests = [{}, {"hmi_sha256": self.manifest["hmi_sha256"]},
                         dict(self.manifest, shim_library_sha256=dict(self.profile["library_sha256"],
                                                                    **{"libhmicom.so": "0" * 64}))]
        for manifest in bad_manifests:
            with self.subTest(manifest=manifest):
                (self.root / "build.json").write_text(json.dumps(manifest))
                with patch.object(self.app, "stop") as stop, \
                        patch.object(self.app, "save_env") as save, \
                        patch.object(server.coding, "apply_changes") as apply, \
                        patch.object(server.coding, "backup") as backup, \
                        patch.object(server.shutil, "rmtree") as remove, \
                        patch.object(server.threading, "Thread") as thread:
                    with self.assertRaisesRegex(server.ApiError, "rebuild"):
                        self.app._flash("test-env", reset=True)
                    for action in (stop, save, apply, backup, remove, thread):
                        action.assert_not_called()
                self.assertEqual(self.env["coding"]["extra"], {"existing": 1})
                self.assertEqual(self.app.rt.state, "running")
                self.assertEqual(snapshot.read_text(), "existing snapshot")
                self.assertEqual(self.app.flashes, {})

    def test_old_manifest_cannot_silently_drop_the_address_table(self):
        for manifest in ({}, {"hmi_sha256": self.manifest["hmi_sha256"]}):
            with self.subTest(manifest=manifest):
                (self.root / "build.json").write_text(json.dumps(manifest))
                with patch.object(builder.mkdisk, "Tree") as tree, \
                        self.assertRaises(builder.BuildError):
                    self.app._rebuild_shim("test-env", self.env)
                tree.assert_not_called()
                self.assertFalse((self.root / "work").exists())


class EarlyShimRefreshTest(ShimRefreshTest):
    version = "006_016_002"


class EarlyAliasShimRefreshTest(EarlyShimRefreshTest):
    shim_profile = "006016"



if __name__ == '__main__':
    unittest.main()
