"""Tests for fail-closed selection of fixed-address HMI shim profiles."""
import unittest

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
