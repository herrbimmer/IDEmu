"""Tests for fail-closed selection of fixed-address HMI shim profiles."""
import unittest
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
        self.assertTrue(builder.shim_libdir({"shim_profile": "006016"}).endswith("/shim/lib-006016"))

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

    def test_006016_requires_each_exact_file_and_cannot_use_other_profiles(self):
        hmi, libraries = firmware_hashes("006016")
        self.assertTrue(builder.validate_shim_profile({"shim_profile": "006016"}, hmi, libraries))
        self.assertIsNone(builder.profile_for_hmi(hmi))
        for selected in ("default", "1803"):
            with self.subTest(selected=selected), self.assertRaises(builder.BuildError):
                builder.validate_shim_profile({"shim_profile": selected}, hmi, libraries)
        for name in libraries:
            for bad in (dict(libraries, **{name: "0" * 64}),
                        {k: v for k, v in libraries.items() if k != name}):
                with self.subTest(name=name, bad=bad), self.assertRaisesRegex(builder.BuildError, name):
                    builder.validate_shim_profile({"shim_profile": "006016"}, hmi, bad)
        other_hmi, other_libraries = firmware_hashes("1803")
        with self.assertRaisesRegex(builder.BuildError, "requires HmiMain3D"):
            builder.validate_shim_profile({"shim_profile": "006016"}, other_hmi, other_libraries)

    def test_006016_build_rejects_other_libc_before_compiling(self):
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
