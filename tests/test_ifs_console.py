"""Regression tests for the supported NBT IFS serial-console records."""
import unittest

from idemu import ifs


class IfsConsoleTest(unittest.TestCase):
    def test_login_is_replaced(self):
        buf = bytearray(b"prefix" + ifs.LOGIN_OLD + b"suffix")
        ifs.select_console_shell(buf)
        self.assertIn(ifs.LOGIN_NEW, buf)
        self.assertNotIn(ifs.LOGIN_OLD, buf)

    def test_existing_ksh_login_is_preserved(self):
        buf = bytearray(b"prefix" + ifs.LOGIN_KSH + b"suffix")
        original = bytes(buf)
        ifs.select_console_shell(buf)
        self.assertEqual(bytes(buf), original)

    def test_unknown_console_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "login/ksh"):
            ifs.select_console_shell(bytearray(b"no console record"))


if __name__ == "__main__":
    unittest.main()
