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
EARLY_VERSION = "006_016_002"
EARLY_HOOKS = (
    "setup_screen_registered", "pmd_fullon", "pm_fullon", "set_power_mode",
    "make_ctrl_event_B", "ccs_push_button", "map_surface_map", "map_surface_unmap",
    "map_notify_update",
)
EARLY_ADDRESSES = set(EARLY_HOOKS) | {"map_redirection_obj"}


def firmware(version):
    return json.loads((REGISTRY / ("nbtevo-" + version + ".json")).read_text())


def expected_records(profile):
    records = {key: int(entry["addr"], 16) for key, entry in profile["hmi_addr"].items()}
    if "runtime" in profile:
        runtime = profile["runtime"]
        records = {key: records.get(key, 0) for key in builder.HMI_ADDR_NAMES}
        records.update(profile_abi=1, **{key: int(runtime[key], 16) for key in
                       ("home_power_flag", "home_aux_flag", "main_home_offset")})
        for key, words in runtime["signatures"].items():
            records.update({"sig_%s_%d" % (key, i): int(word, 16) for i, word in enumerate(words)})
    return records


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
        for version in VERSIONS + (EARLY_VERSION,):
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

    def test_006_profile_contains_only_its_ten_sites_and_complete_runtime_contract(self):
        profile = firmware(EARLY_VERSION)
        self.assertEqual(builder.profile_for_hmi(profile["hmi_sha256"]), profile)
        self.assertFalse(profile.get("status", "").startswith("stub"))
        self.assertEqual(set(profile["hmi_addr"]), EARLY_ADDRESSES)
        self.assertEqual(set(profile["runtime"]), {"abi", "home_power_flag", "home_aux_flag",
                                                  "main_home_offset", "signatures"})
        self.assertEqual(profile["runtime"]["abi"], "id5_1803")
        self.assertEqual(profile["runtime"]["home_power_flag"], "0x577")
        self.assertEqual(profile["runtime"]["home_aux_flag"], "0x576")
        self.assertEqual(profile["runtime"]["main_home_offset"], "0x958")
        self.assertEqual(set(profile["runtime"]["signatures"]), set(EARLY_HOOKS))
        for key, words in profile["runtime"]["signatures"].items():
            with self.subTest(hook=key):
                self.assertEqual(len(words), 4)
                self.assertTrue(all(0 < int(word, 16) <= 0xffffffff for word in words))
        records = expected_records(profile)
        self.assertEqual(len(records), 69)
        self.assertEqual({key for key in builder.HMI_ADDR_NAMES if records[key]}, EARLY_ADDRESSES)

    def test_1803_remains_separate_from_the_007_address_registry(self):
        hashes = dict(builder.SHIM_PROFILES["1803"])
        hmi = hashes.pop("hmi")
        self.assertIsNone(builder.profile_for_hmi(hmi))
        self.assertTrue(builder.validate_shim_profile({"shim_profile": "1803"}, hmi, hashes))
        self.assertNotEqual(builder.shim_libdir({}), builder.shim_libdir({"shim_profile": "1803"}))
        with self.assertRaises(builder.BuildError):
            builder.validate_shim_profile({}, hmi, hashes)
        for version in VERSIONS + (EARLY_VERSION,):
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

    def test_006_partial_or_unknown_runtime_metadata_is_rejected_before_image_writes(self):
        profile = firmware(EARLY_VERSION)
        malformed = []
        for key in ("runtime",):
            bad = copy.deepcopy(profile); del bad[key]; malformed.append(bad)
        for value in (None, {}, {"abi": "id5_1803"}):
            bad = copy.deepcopy(profile); bad["runtime"] = value; malformed.append(bad)
        for key in profile["runtime"]:
            bad = copy.deepcopy(profile); del bad["runtime"][key]; malformed.append(bad)
        for key, value in (("abi", "unknown"), ("unknown", "0x1"),
                           ("home_power_flag", "0x0"), ("home_power_flag", "0x10000"),
                           ("home_aux_flag", "0x577"), ("home_aux_flag", 0x576),
                           ("main_home_offset", "0x959"), ("main_home_offset", "0x10000"),
                           ("main_home_offset", "not-hex")):
            bad = copy.deepcopy(profile); bad["runtime"][key] = value; malformed.append(bad)
        for name in EARLY_ADDRESSES:
            bad = copy.deepcopy(profile); del bad["hmi_addr"][name]; malformed.append(bad)
        bad = copy.deepcopy(profile)
        bad["hmi_addr"]["eds_display_enable"] = {"addr": "0x1000"}
        malformed.append(bad)
        for value in (None, "not-a-sha256", "0" * 63):
            bad = copy.deepcopy(profile); bad["libc_sha256"] = value; malformed.append(bad)
        bad = copy.deepcopy(profile); del bad["libc_sha256"]; malformed.append(bad)
        for name in EARLY_HOOKS:
            bad = copy.deepcopy(profile); del bad["runtime"]["signatures"][name]; malformed.append(bad)
        bad = copy.deepcopy(profile)
        bad["runtime"]["signatures"]["map_redirection_obj"] = ["0x1"] * 4
        malformed.append(bad)
        for words in (["0x1"] * 3, ["0x1"] * 5, ["0x1", "0x0", "0x1", "0x1"],
                      ["0x1", "not-hex", "0x1", "0x1"], ["0x1", "0x100000000", "0x1", "0x1"],
                      [1, 2, 3, 4]):
            bad = copy.deepcopy(profile); bad["runtime"]["signatures"][EARLY_HOOKS[0]] = words
            malformed.append(bad)
        for index, bad in enumerate(malformed):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "data/firmwares"
                directory.mkdir(parents=True)
                (directory / "bad.json").write_text(json.dumps(bad))
                with patch.object(builder, "HERE", tmp), patch.object(builder.mkdisk, "Tree") as tree:
                    with self.assertRaises(builder.BuildError):
                        builder.build_shim({}, "/unused", "/unused/shim.img",
                                           hmi_sha=profile["hmi_sha256"], library_hashes=profile["library_sha256"])
                    tree.assert_not_called()

    def test_packaging_writes_the_selected_legacy_or_extended_address_table(self):
        cases = [({}, firmware(version)["hmi_sha256"], firmware(version)["library_sha256"])
                 for version in VERSIONS + (EARLY_VERSION,)]
        early = firmware(EARLY_VERSION)
        cases.append(({"shim_profile": "006016"}, early["hmi_sha256"], early["library_sha256"]))
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
                        lines = table.src.decode().splitlines()
                        actual = {key: int(value, 16) for key, value in (line.split() for line in lines)}
                        self.assertEqual(len(lines), len(actual), "duplicate addr.tab records")
                        expected = expected_records(builder.profile_for_hmi(hmi))
                        self.assertEqual(actual, expected)
                        self.assertEqual(len(actual), 69 if hmi == early["hmi_sha256"] else 29)

    def test_unverified_registry_cannot_write_a_shim(self):
        with patch.object(builder.mkdisk, "Tree") as tree:
            for version in ("007_001_016", EARLY_VERSION):
                profile = firmware(version)
                for libraries in ({}, dict(profile["library_sha256"], **{"libhmicom.so": "0" * 64})):
                    with self.subTest(version=version, libraries=libraries), self.assertRaises(builder.BuildError):
                        builder.build_shim({}, "/unused", "/unused/shim.img", hmi_sha=profile["hmi_sha256"],
                                           library_hashes=libraries)
            with self.assertRaisesRegex(builder.BuildError, "rebuild"):
                builder.build_shim({}, "/unused", "/unused/shim.img")
            with self.assertRaisesRegex(builder.BuildError, "exact HMI"):
                builder.build_shim({}, "/unused", "/unused/shim.img", hmi_sha="0" * 64,
                                   library_hashes=firmware(EARLY_VERSION)["library_sha256"])
            # Losing the JSON entry must not downgrade exact006 to unverified 051 defaults.
            early = firmware(EARLY_VERSION)
            with patch.object(builder, "profile_for_hmi", return_value=None), self.assertRaises(builder.BuildError):
                builder.build_shim({}, "/unused", "/unused/shim.img", hmi_sha=early["hmi_sha256"],
                                   library_hashes=early["library_sha256"])
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
