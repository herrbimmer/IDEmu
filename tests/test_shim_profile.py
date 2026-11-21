"""Tests for fail-closed selection of fixed-address HMI shim profiles."""
import unittest
import json
import os
from pathlib import Path
import subprocess
import tempfile

from idemu import builder


def firmware_hashes(profile):
    hashes = dict(builder.SHIM_PROFILES[profile])
    hmi = hashes.pop("hmi")
    return hmi, hashes


class ShimProfileTest(unittest.TestCase):
    def test_default_and_profile_directories_are_separate(self):
        self.assertTrue(builder.shim_libdir({}).endswith("/shim/lib"))
        self.assertTrue(builder.shim_libdir({"shim_profile": "default"}).endswith("/shim/lib"))
        self.assertTrue(builder.shim_libdir({"shim_profile": "1803"}).endswith("/shim/lib-1803"))
        self.assertEqual(builder.shim_libdir({"shim_profile": "006016"}), builder.shim_libdir({}))

    def test_profile_name_cannot_escape(self):
        with self.assertRaises(builder.BuildError):
            builder.shim_libdir({"shim_profile": "../lib"})

    def test_profile_requires_the_exact_hmi_and_hooked_libraries(self):
        hmi, libraries = firmware_hashes("1803")
        self.assertTrue(builder.validate_shim_profile({"shim_profile": "1803"}, hmi, libraries))
        with self.assertRaisesRegex(builder.BuildError, "requires HmiMain3D"):
            builder.validate_shim_profile({"shim_profile": "1803"}, "wrong", libraries)
        libraries["libhmicom.so"] = "wrong"
        with self.assertRaisesRegex(builder.BuildError, "requires libhmicom.so"):
            builder.validate_shim_profile({"shim_profile": "1803"}, hmi, libraries)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(builder.BuildError, "no registered HmiMain3D hash"):
            builder.validate_shim_profile({"shim_profile": "unknown"}, "anything")

    def test_006016_uses_the_registry_and_old_environment_name_is_only_an_alias(self):
        profile = json.loads((Path(builder.HERE) / "data/firmwares/nbtevo-006_016_002.json").read_text())
        hmi, libraries = profile["hmi_sha256"], profile["library_sha256"]
        self.assertNotIn("006016", builder.SHIM_PROFILES)
        self.assertEqual(builder.profile_for_hmi(hmi), profile)
        for env in ({}, {"shim_profile": "default"}, {"shim_profile": "006016"}):
            with self.subTest(env=env):
                self.assertTrue(builder.validate_shim_profile(env, hmi, libraries))
                self.assertEqual(builder.shim_firmware(env, hmi, libraries), profile)
        with self.assertRaises(builder.BuildError):
            builder.validate_shim_profile({"shim_profile": "1803"}, hmi, libraries)
        for name in libraries:
            for bad in (dict(libraries, **{name: "0" * 64}),
                        {k: v for k, v in libraries.items() if k != name}):
                with self.subTest(name=name, bad=bad), self.assertRaisesRegex(builder.BuildError, name):
                    builder.validate_shim_profile({"shim_profile": "006016"}, hmi, bad)
                self.assertFalse(builder.validate_shim_profile({}, hmi, bad))
        wrong_sets = [firmware_hashes("1803"), firmware_hashes("default"), ("0" * 64, libraries)]
        for wrong_hmi, wrong_libraries in wrong_sets:
            with self.subTest(hmi=wrong_hmi), self.assertRaises(builder.BuildError):
                builder.validate_shim_profile({"shim_profile": "006016"}, wrong_hmi, wrong_libraries)

    def test_old_006_build_name_still_rejects_wrong_libc_before_compiling(self):
        script = Path(builder.HERE).parents[0] / "src/shim/build.sh"
        with tempfile.TemporaryDirectory() as directory:
            libc = Path(directory) / "libc.so.3"
            libc.write_bytes(b"a different firmware libc")
            result = subprocess.run(["bash", str(script), str(libc)],
                                    env=dict(os.environ, SHIM_PROFILE="006016"),
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires firmware libc SHA256", result.stderr)

    def test_registered_profile_hmi_cannot_use_default_shim(self):
        hmi, libraries = firmware_hashes("1803")
        with self.assertRaisesRegex(builder.BuildError, "requires shim profile 1803"):
            builder.validate_shim_profile({}, hmi, libraries)

    def test_default_validation_requires_the_complete_2403_set(self):
        hmi, libraries = firmware_hashes("default")
        self.assertTrue(builder.validate_shim_profile({}, hmi, libraries))
        self.assertFalse(builder.validate_shim_profile({}, hmi, {}))
        self.assertFalse(builder.validate_shim_profile({}, "unregistered", {}))


if __name__ == "__main__":
    unittest.main()
