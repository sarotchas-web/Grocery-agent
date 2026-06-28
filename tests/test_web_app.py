from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.crypto import EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import DeliveryProfileStore, MASKED_DELIVERY_ADDRESS
from grocery_agent.models import Role, User
from grocery_agent.shufersal_adapter import ShufersalProduct
from grocery_agent.web_app import (
    render_home,
    render_profile_form,
    render_shufersal_search,
    update_delivery_profile_from_form,
)


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
        self.assertIn("\u05de\u05d6\u05d4\u05d4 \u05e4\u05e8\u05d5\u05e4\u05d9\u05dc: dp_web_test", html)
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
        self.assertIn("\u05d1\u05d7\u05d9\u05e8\u05ea \u05de\u05e9\u05dc\u05d5\u05d7 \u05d0\u05d5 \u05d0\u05d9\u05e1\u05d5\u05e3", html)

    def test_home_renders_budget_amounts_with_shekel_symbol(self) -> None:
        html = render_home(self.michal, self.store)

        self.assertIn("\u20aa800.00", html)
        self.assertIn("\u20aa800.01", html)

    def test_portal_uses_hebrew_rtl_interface(self) -> None:
        home = render_home(self.michal, self.store)
        profile = render_profile_form(self.shay)

        self.assertIn('<html lang="he" dir="rtl">', home)
        self.assertIn("\u05d4\u05d6\u05de\u05e0\u05d4 \u05d7\u05d3\u05e9\u05d4", home)
        self.assertIn("\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7", profile)
        self.assertNotIn("New order", home)
        self.assertNotIn("Delivery Profile", profile)
        self.assertNotIn("Back", profile)
    def test_shufersal_search_renders_public_price_only(self) -> None:
        product = ShufersalProduct(
            item_code="7290000000001",
            name="\u05de\u05d5\u05e6\u05e8 \u05d1\u05d3\u05d9\u05e7\u05d4",
            price_ils=Decimal("12.30"),
            unit_quantity="\u05d9\u05d7\u05d9\u05d3\u05d4",
            quantity=Decimal("1"),
            unit_of_measure="\u05d9\u05d7\u05d9\u05d3\u05d4",
            unit_price_ils=Decimal("12.30"),
            weighted=False,
            updated_at="2099-01-01T03:00:00",
        )

        html = render_shufersal_search("michal", "\u05de\u05d5\u05e6\u05e8", (product,))

        self.assertIn("\u05d7\u05d9\u05e4\u05d5\u05e9 \u05de\u05d7\u05d9\u05e8\u05d9 \u05de\u05d5\u05e6\u05e8\u05d9\u05dd", html)
        self.assertIn("\u20aa12.30", html)
        self.assertNotIn("blob.core.windows.net", html)
        self.assertNotIn("sig=", html)

if __name__ == "__main__":
    unittest.main()
