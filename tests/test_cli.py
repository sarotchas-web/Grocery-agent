from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.cli import main
from grocery_agent.delivery_profile import MASKED_DELIVERY_ADDRESS


SENSITIVE_TEST_ADDRESS = "SENSITIVE_CLI_ADDRESS_TOKEN_456"


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GROCERY_AGENT_MASTER_KEY"] = "unit-test-master-key-only"
        self.tmp = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.tmp.mkdir(exist_ok=True)
        self.profile_path = self.tmp / "cli-profile.enc"
        self.profile_path.unlink(missing_ok=True)

    def test_owner_can_update_profile_without_printing_address(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "--profile-path",
                    str(self.profile_path),
                    "delivery-profile-update",
                    "--actor",
                    "shay",
                    "--city",
                    "Pardesiya",
                    "--address-line",
                    SENSITIVE_TEST_ADDRESS,
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn(MASKED_DELIVERY_ADDRESS, output.getvalue())
        self.assertIn("delivery_profile_id=", output.getvalue())
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, output.getvalue())
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, self.profile_path.read_text(encoding="utf-8"))

    def test_household_member_cannot_update_profile(self) -> None:
        with self.assertRaises(PermissionError):
            main(
                [
                    "--profile-path",
                    str(self.profile_path),
                    "delivery-profile-update",
                    "--actor",
                    "michal",
                    "--city",
                    "Pardesiya",
                    "--address-line",
                    SENSITIVE_TEST_ADDRESS,
                ]
            )

    def test_show_profile_prints_only_masked_address(self) -> None:
        setup_output = io.StringIO()
        with contextlib.redirect_stdout(setup_output):
            main(
                [
                    "--profile-path",
                    str(self.profile_path),
                    "delivery-profile-update",
                    "--actor",
                    "shay",
                    "--city",
                    "Pardesiya",
                    "--address-line",
                    SENSITIVE_TEST_ADDRESS,
                    "--profile-id",
                    "dp_cli_test",
                ]
            )
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            code = main(
                [
                    "--profile-path",
                    str(self.profile_path),
                    "delivery-profile-show",
                    "--actor",
                    "michal",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn(MASKED_DELIVERY_ADDRESS, output.getvalue())
        self.assertIn("delivery_profile_id=dp_cli_test", output.getvalue())
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, output.getvalue())


if __name__ == "__main__":
    unittest.main()

