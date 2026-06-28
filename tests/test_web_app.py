from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.crypto import EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import DeliveryProfileStore, MASKED_DELIVERY_ADDRESS
from grocery_agent.models import Role, User
from grocery_agent.web_app import render_home, render_profile_form, update_delivery_profile_from_form


SENSITIVE_TEST_ADDRESS = "SENSITIVE_WEB_ADDRESS_TOKEN_789"


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GROCERY_AGENT_MASTER_KEY"] = "unit-test-master-key-only"
        tmp = Path(__file__).resolve().parents[1] / ".test-tmp"
        tmp.mkdir(exist_ok=True)
        self.profile_path = tmp / "web-profile.enc"
        self.profile_path.unlink(missing_ok=True)
        self.store = DeliveryProfileStore(self.profile_path, EnvMasterKeyCryptoProvider.from_env())
        self.shay = User(id="shay", display_name="Shay", role=Role.OWNER)
        self.michal = User(id="michal", display_name="Michal", role=Role.HOUSEHOLD_MEMBER)

    def test_owner_profile_update_renders_only_masked_address(self) -> None:
        html = update_delivery_profile_from_form(
            self.shay,
            {
                "city": "Pardesiya",
                "address_line": SENSITIVE_TEST_ADDRESS,
                "recipient_note": "synthetic",
                "profile_id": "dp_web_test",
            },
            self.store,
        )

        self.assertIn(MASKED_DELIVERY_ADDRESS, html)
        self.assertIn("delivery_profile_id=dp_web_test", html)
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, html)
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, self.profile_path.read_text(encoding="utf-8"))

    def test_michal_profile_form_is_disabled(self) -> None:
        html = render_profile_form(self.michal)

        self.assertIn("disabled", html)
        self.assertIn(MASKED_DELIVERY_ADDRESS, html)

    def test_home_uses_masked_profile_summary(self) -> None:
        update_delivery_profile_from_form(
            self.shay,
            {"city": "Pardesiya", "address_line": SENSITIVE_TEST_ADDRESS, "profile_id": "dp_home_test"},
            self.store,
        )

        html = render_home(self.michal, self.store)

        self.assertIn(MASKED_DELIVERY_ADDRESS, html)
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, html)
        self.assertIn("Choose delivery or pickup", html)

    def test_home_renders_budget_amounts_with_shekel_symbol(self) -> None:
        html = render_home(self.michal, self.store)

        self.assertIn("\u20aa800.00", html)
        self.assertIn("\u20aa800.01", html)

if __name__ == "__main__":
    unittest.main()
