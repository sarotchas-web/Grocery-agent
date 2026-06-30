from __future__ import annotations

import os
import sys
import threading
import unittest
import urllib.parse
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.crypto import EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import DeliveryProfileStore, MASKED_DELIVERY_ADDRESS
from grocery_agent.models import Role, User
from grocery_agent.shufersal_adapter import ShufersalProduct
from grocery_agent.shufersal_promotions import (
    ShufersalConnectionStatus,
    ShufersalProductOffer,
)
from grocery_agent.web_app import (
    build_handler,
    render_home,
    render_profile_form,
    render_shufersal_match_form,
    render_shufersal_search,
    render_shufersal_status,
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
    def test_shufersal_status_renders_only_safe_public_metadata(self) -> None:
        html = render_shufersal_status(
            "michal",
            ShufersalConnectionStatus(
                product_count=123,
                promotion_count=45,
                latest_price_update="2099-01-01T03:00:00",
            ),
        )

        self.assertIn("123", html)
        self.assertIn("45", html)
        self.assertIn("2099-01-01T03:00:00", html)
        self.assertNotIn("blob.core.windows.net", html)
        self.assertNotIn("sig=", html)

    def test_new_order_match_page_shows_live_options_and_manual_fallback(self) -> None:
        product = _synthetic_product()
        offer = ShufersalProductOffer(product, (), Decimal("12.30"))

        html = render_shufersal_match_form(
            "michal",
            "<synthetic milk>",
            (("<synthetic milk>", (offer,)),),
        )

        self.assertIn('action="/orders/shufersal-match"', html)
        self.assertIn('name="selection_0" value="7290000000001"', html)
        self.assertIn("\u20aa12.30", html)
        self.assertIn('action="/orders/quotes/manual"', html)
        self.assertNotIn("<synthetic milk>", html)
        self.assertIn("&lt;synthetic milk&gt;", html)
        self.assertNotIn("sig=", html)

    def test_new_order_http_flow_prefills_selected_live_product(self) -> None:
        product = _synthetic_product()
        offer = ShufersalProductOffer(product, (), Decimal("12.30"))

        class FakeOfferClient:
            def search(self, query: str, limit: int = 20):
                if query in ("\u05d7\u05dc\u05d1", product.item_code):
                    return (offer,)
                return ()

        handler = build_handler(self.profile_path, shufersal_client=FakeOfferClient())
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            match_response = _post_form(
                base + "/orders/quotes",
                {"actor": "michal", "items": "\u05d7\u05dc\u05d1"},
            )
            self.assertIn('name="selection_0"', match_response)
            quote_response = _post_form(
                base + "/orders/shufersal-match",
                {
                    "actor": "michal",
                    "items": "\u05d7\u05dc\u05d1",
                    "selection_0": product.item_code,
                },
            )
            self.assertIn('name="a_retailer" value="\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE"', quote_response)
            self.assertIn('name="a_subtotal" type="number" min="0" step="0.01" value="12.30"', quote_response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
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

        offer = ShufersalProductOffer(product, (), Decimal("12.30"))
        html = render_shufersal_search("michal", "\u05de\u05d5\u05e6\u05e8", (offer,))

        self.assertIn("\u05d7\u05d9\u05e4\u05d5\u05e9 \u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d5\u05de\u05d1\u05e6\u05e2\u05d9\u05dd", html)
        self.assertIn("\u20aa12.30", html)
        self.assertNotIn("blob.core.windows.net", html)
        self.assertNotIn("sig=", html)

def _synthetic_product() -> ShufersalProduct:
    return ShufersalProduct(
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


def _post_form(url: str, form: dict[str, str]) -> str:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read().decode("utf-8")

if __name__ == "__main__":
    unittest.main()
