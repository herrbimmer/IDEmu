"""Firmware registry regressions: address tables never bypass exact binary validation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from idemu import builder


REGISTRY = Path(builder.HERE) / "data" / "firmwares"
VERSIONS = ("007_001_016", "007_030_001", "007_039_008", "007_051_002")


def firmware(version):
    return json.loads((REGISTRY / ("nbtevo-" + version + ".json")).read_text())


class FirmwareRegistryTest(unittest.TestCase):
    def test_all_shipped_firmwares_have_complete_address_tables(self):
        self.assertEqual(len(builder.HMI_ADDR_NAMES), 29)
        for version in VERSIONS:
            with self.subTest(version=version):
                expected = firmware(version)
                actual = builder.profile_for_hmi(expected["hmi_sha256"])
                self.assertEqual(actual, expected)
                self.assertEqual(set(actual["hmi_addr"]), set(builder.HMI_ADDR_NAMES))
                self.assertEqual(set(actual["library_sha256"]), {"libhmicom.so", "libhmicoding.so"})
                for entry in actual["hmi_addr"].values():
                    value = int(entry["addr"], 16)
                    self.assertGreater(value, 0)
                    self.assertLessEqual(value, 0xffffffff)
                    self.assertEqual(value % 4, 0)

    def test_every_registered_hmi_needs_both_exact_companion_libraries(self):
        for version in VERSIONS:
            profile = firmware(version)
            hmi, libraries = profile["hmi_sha256"], profile["library_sha256"]
            with self.subTest(version=version):
                self.assertTrue(builder.validate_shim_profile({}, hmi, libraries))
                self.assertFalse(builder.validate_shim_profile({}, hmi, {}))
                for name in libraries:
                    missing = dict(libraries)
                    missing.pop(name)
                    wrong = dict(libraries, **{name: "0" * 64})
                    self.assertFalse(builder.validate_shim_profile({}, hmi, missing), name)
                    self.assertFalse(builder.validate_shim_profile({}, hmi, wrong), name)

    def test_1803_remains_separate_from_the_007_address_registry(self):
        hashes = dict(builder.SHIM_PROFILES["1803"])
        hmi = hashes.pop("hmi")
        self.assertIsNone(builder.profile_for_hmi(hmi))
        self.assertTrue(builder.validate_shim_profile({"shim_profile": "1803"}, hmi, hashes))
        self.assertNotEqual(builder.shim_libdir({}), builder.shim_libdir({"shim_profile": "1803"}))
        with self.assertRaises(builder.BuildError):
            builder.validate_shim_profile({}, hmi, hashes)
        for version in VERSIONS:
            profile = firmware(version)
            with self.subTest(version=version), self.assertRaises(builder.BuildError):
                builder.validate_shim_profile({"shim_profile": "1803"}, profile["hmi_sha256"],
                                              profile["library_sha256"])
        with self.assertRaises(builder.BuildError):
            builder.validate_shim_profile({"shim_profile": "unknown"}, hmi, hashes)
        self.assertIsNone(builder.profile_for_hmi("0" * 64))
        self.assertFalse(builder.validate_shim_profile({}, "0" * 64, hashes))

    def test_registry_cannot_claim_the_separate_1803_hmi(self):
        libraries = dict(builder.SHIM_PROFILES["1803"])
        hmi = libraries.pop("hmi")
        collision = firmware("007_051_002")
        collision["hmi_sha256"] = hmi
        collision["library_sha256"] = libraries
        for env in ({}, {"shim_profile": "default"}):
            with self.subTest(env=env), patch.object(builder, "profile_for_hmi", return_value=collision) as lookup:
                with self.assertRaisesRegex(builder.BuildError, "requires shim profile 1803"):
                    builder.validate_shim_profile(env, hmi, libraries)
                lookup.assert_not_called()

    def test_duplicate_hmi_profiles_are_rejected(self):
        profile = firmware("007_051_002")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data" / "firmwares"
            directory.mkdir(parents=True)
            for name in ("original.json", "duplicate.json"):
                (directory / name).write_text(json.dumps(profile))
            with patch.object(builder, "HERE", tmp), self.assertRaises(builder.BuildError):
                builder.profile_for_hmi(profile["hmi_sha256"])

    def test_malformed_working_profiles_are_rejected(self):
        profile = firmware("007_051_002")
        key = "setup_screen_registered"
        bad_profiles = []
        for address in ("not-hex", "0x0", "0x123", "0x100000000", 0x2f9308):
            bad = copy.deepcopy(profile)
            bad["hmi_addr"][key]["addr"] = address
            bad_profiles.append(bad)
        bad = copy.deepcopy(profile)
        del bad["hmi_addr"][key]
        bad_profiles.append(bad)
        bad = copy.deepcopy(profile)
        bad["hmi_addr"]["unknown_hook"] = {"addr": "0x1000"}
        bad_profiles.append(bad)
        bad = copy.deepcopy(profile)
        del bad["library_sha256"]
        bad_profiles.append(bad)
        bad = copy.deepcopy(profile)
        bad["library_sha256"]["libhmicom.so"] = "not-a-sha256"
        bad_profiles.append(bad)
        bad = copy.deepcopy(profile)
        bad["hmi_sha256"] = "not-a-sha256"
        bad_profiles.append(bad)
        for index, bad in enumerate(bad_profiles):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "data" / "firmwares"
                directory.mkdir(parents=True)
                (directory / "bad.json").write_text(json.dumps(bad))
                with patch.object(builder, "HERE", tmp), self.assertRaises(builder.BuildError):
                    builder.profile_for_hmi(profile["hmi_sha256"])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data" / "firmwares"
            directory.mkdir(parents=True)
            (directory / "broken.json").write_text("{broken JSON")
            with patch.object(builder, "HERE", tmp), self.assertRaises(builder.BuildError):
                builder.profile_for_hmi(profile["hmi_sha256"])

    def test_packaging_writes_only_the_selected_007_address_table(self):
        cases = [({}, firmware(version)["hmi_sha256"], firmware(version)["library_sha256"])
                 for version in VERSIONS]
        hashes = dict(builder.SHIM_PROFILES["1803"])
        cases.append(({"shim_profile": "1803"}, hashes.pop("hmi"), hashes))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "os/opt/sys/etc").mkdir(parents=True)
            (root / "os/etc").mkdir()
            (root / "lib").mkdir()
            processes = ["<Process><Name>/opt/sys/bin/%s</Name><Args>%s</Args></Process>" %
                         (name, args.lstrip("=")) for name, args, _ in builder.SERVICES]
            (root / "os/opt/sys/etc/starter.cfg").write_text("\n".join(processes))
            (root / "os/etc/io-ipc-o5.cfg").write_text("tchannel=original\n")
            for env, hmi, libraries in cases:
                with self.subTest(hmi=hmi), \
                        patch.object(builder, "shim_libdir", return_value=str(root / "lib")), \
                        patch.object(builder.codegen, "profile_for", return_value={}), \
                        patch.object(builder.codegen, "build_table", return_value=(b"", 0, [])), \
                        patch.object(builder.mkdisk, "write") as write:
                    builder.build_shim(env, str(root / "os"), str(root / "shim.img"), log=lambda _: None,
                                       hmi_sha=hmi, library_hashes=libraries)
                    table = write.call_args.args[0].get("/addr.tab")
                    if env.get("shim_profile") == "1803":
                        self.assertIsNone(table)
                    else:
                        expected = {key: entry["addr"] for key, entry in builder.profile_for_hmi(hmi)["hmi_addr"].items()}
                        self.assertEqual(dict(line.split() for line in table.src.decode().splitlines()), expected)

    def test_unverified_registry_cannot_write_a_shim(self):
        profile = firmware("007_001_016")
        with patch.object(builder.mkdisk, "Tree") as tree:
            for libraries in ({}, dict(profile["library_sha256"], **{"libhmicom.so": "0" * 64})):
                with self.subTest(libraries=libraries), self.assertRaisesRegex(builder.BuildError, "exact HMI"):
                    builder.build_shim({}, "/unused", "/unused/shim.img", hmi_sha=profile["hmi_sha256"],
                                       library_hashes=libraries)
            with self.assertRaisesRegex(builder.BuildError, "rebuild"):
                builder.build_shim({}, "/unused", "/unused/shim.img")
            tree.assert_not_called()

    def test_unfinished_local_profile_is_not_applied(self):
        stub = {"status": "stub", "hmi_sha256": "1" * 64, "hmi_addr": {}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data" / "firmwares"
            directory.mkdir(parents=True)
            (directory / "stub.json").write_text(json.dumps(stub))
            with patch.object(builder, "HERE", tmp):
                self.assertIsNone(builder.profile_for_hmi(stub["hmi_sha256"]))


if __name__ == "__main__":
    unittest.main()
