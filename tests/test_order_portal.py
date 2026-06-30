from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.budget import BUDGET_ACK_TEXT_HE
from grocery_agent.models import FulfillmentMode
from grocery_agent.order_portal import (
    RetailerQuotePrefill,
    compare_order_form,
    parse_shopping_list,
    render_approval,
    render_comparison,
    render_new_order_form,
    render_quote_form,
)


def quote_form(total: str = "700.00") -> dict[str, str]:
    return {
        "actor": "michal",
        "items": "Milk\nBread",
        "a_retailer": "Retailer A",
        "a_subtotal": total,
        "a_discounts": "0",
        "a_promotions": "0",
        "a_delivery_fee": "0",
        "a_service_fee": "0",
        "a_available": "yes",
    }


class OrderPortalTests(unittest.TestCase):
    def test_michal_can_start_a_list_without_address_data(self) -> None:
        html = render_new_order_form("michal")

        self.assertIn('action="/orders/quotes"', html)
        self.assertIn('name="actor" value="michal"', html)
        self.assertNotIn("address", html.lower())

    def test_list_and_quote_forms_escape_user_input(self) -> None:
        self.assertEqual(parse_shopping_list(" Milk \n\n Bread "), ("Milk", "Bread"))

        html = render_quote_form("michal", "<script>alert(1)</script>")

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_comparison_uses_discounts_and_all_fees(self) -> None:
        form = quote_form("850")
        form.update(
            {
                "a_discounts": "25",
                "a_promotions": "15",
                "a_delivery_fee": "20",
                "a_service_fee": "5",
            }
        )

        comparison = compare_order_form(form)

        self.assertEqual(comparison.recommendation.orders[0].final_total, 835)

    def test_only_eligible_pickup_is_recommended(self) -> None:
        form = quote_form("700")
        form.update(
            {
                "a_delivery_fee": "25",
                "a_pickup": "yes",
                "a_pickup_name": "Collection Point",
                "a_pickup_area": "Emek Hefer",
                "a_pickup_start": "17:00",
                "a_pickup_end": "18:00",
                "a_pickup_fee": "0",
            }
        )

        comparison = compare_order_form(form)

        self.assertEqual(comparison.recommendation.orders[0].mode, FulfillmentMode.PICKUP)
        html = render_comparison("michal", comparison)
        self.assertIn("Collection Point", html)
        self.assertIn("17:00\u201318:00 \u05e9\u05e2\u05d5\u05df \u05d9\u05e9\u05e8\u05d0\u05dc", html)

    def test_ineligible_pickup_falls_back_to_delivery(self) -> None:
        form = quote_form("700")
        form.update(
            {
                "a_pickup": "yes",
                "a_pickup_name": "Wrong Area",
                "a_pickup_area": "Sharon",
                "a_pickup_start": "17:00",
                "a_pickup_end": "18:00",
                "a_pickup_fee": "0",
            }
        )

        comparison = compare_order_form(form)

        self.assertEqual(comparison.recommendation.orders[0].mode, FulfillmentMode.DELIVERY)
        self.assertNotIn("Wrong Area", render_comparison("michal", comparison))

    def test_budget_acknowledgement_boundary_is_rendered_and_enforced(self) -> None:
        at_limit = render_comparison("michal", compare_order_form(quote_form("800.00")))
        over_limit = render_comparison("michal", compare_order_form(quote_form("800.01")))

        self.assertNotIn('name="budget_ack"', at_limit)
        self.assertIn('name="budget_ack"', over_limit)
        self.assertIn(BUDGET_ACK_TEXT_HE, over_limit)
        with self.assertRaises(PermissionError):
            render_approval({"estimated_total": "800.01", "strategy": "one_retailer_delivery"})
        approved = render_approval(
            {
                "estimated_total": "800.01",
                "strategy": "one_retailer_delivery",
                "budget_ack": "yes",
            }
        )
        self.assertIn("\u05d0\u05d5\u05e9\u05e8", approved)

    def test_live_shufersal_prefill_requires_manual_availability_and_fees(self) -> None:
        html = render_quote_form(
            "michal",
            "synthetic product x 2",
            prefill=RetailerQuotePrefill(
                retailer="\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE",
                subtotal=Decimal("20.00"),
                promotions=Decimal("3.00"),
                weighted=True,
            ),
        )

        self.assertIn('name="a_retailer" value="\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE"', html)
        self.assertIn('name="a_subtotal" type="number" min="0" step="0.01" value="20.00"', html)
        self.assertIn('name="a_promotions" type="number" min="0" step="0.01" value="3.00"', html)
        self.assertIn('name="a_delivery_fee" type="number" min="0" step="0.01" value="" required', html)
        self.assertNotIn('name="a_available" value="yes" checked', html)
        self.assertIn('name="a_weighted" value="yes" checked', html)

    def test_order_forms_use_hebrew_labels(self) -> None:
        new_order = render_new_order_form("michal")
        quotes = render_quote_form("michal", "\u05d7\u05dc\u05d1")

        self.assertIn("\u05d1\u05e0\u05d9\u05d9\u05ea \u05e8\u05e9\u05d9\u05de\u05ea \u05d4\u05e7\u05e0\u05d9\u05d5\u05ea", new_order)
        self.assertIn("\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9\u05dd", quotes)
        self.assertNotIn("Build your shopping list", new_order)
        self.assertNotIn("Retailer comparison", quotes)
        self.assertNotIn("Compare options", quotes)

if __name__ == "__main__":
    unittest.main()
