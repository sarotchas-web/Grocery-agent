from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grocery_agent.budget import BUDGET_ACK_TEXT_HE, BudgetPolicy
from grocery_agent.crypto import EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import (
    MASKED_DELIVERY_ADDRESS,
    DeliveryAddress,
    DeliveryProfileAdminForm,
    DeliveryProfileStore,
    audit_delivery_profile_used,
    profile_api_response,
    profile_email_fragment,
)
from grocery_agent.logging_safety import RedactingLogger
from grocery_agent.models import (
    BasketItem,
    Discounts,
    Fees,
    FulfillmentMode,
    OrderEstimate,
    PickupPoint,
    RetailerOffer,
    Role,
    TimeWindow,
    User,
    money,
)
from grocery_agent.permissions import can
from grocery_agent.pickup import PickupPreference, eligible_pickup_estimates, pickup_summary
from grocery_agent.recommendation import recommend


SHAY = User(id="shay", display_name="Shay", role=Role.OWNER)
MICHAL = User(id="michal", display_name="Michal", role=Role.HOUSEHOLD_MEMBER)
SENSITIVE_TEST_ADDRESS = "SENSITIVE_PROFILE_TOKEN_123"


def item(sku: str = "milk", price: str = "100", available: bool = True) -> BasketItem:
    return BasketItem(sku=sku, name=f"Item {sku}", quantity=Decimal("1"), unit_price=Decimal(price), available=available)


def weighted_item() -> BasketItem:
    return BasketItem(
        sku="apples",
        name="Weighted apples",
        quantity=Decimal("1"),
        unit_price=Decimal("12.50"),
        weighted=True,
        estimated_weight_kg=Decimal("2.4"),
    )


def order(
    retailer: str = "Retailer A",
    total_item_price: str = "100",
    mode: FulfillmentMode = FulfillmentMode.DELIVERY,
    items: tuple[BasketItem, ...] | None = None,
    delivery_fee: str = "0",
    service_fee: str = "0",
    pickup_fee: str = "0",
    item_discounts: str = "0",
    promotions: str = "0",
    pickup_name: str | None = None,
    pickup_area: str | None = None,
    window: TimeWindow | None = None,
) -> OrderEstimate:
    basket = items if items is not None else (item(price=total_item_price),)
    return OrderEstimate(
        retailer=retailer,
        mode=mode,
        items=basket,
        discounts=Discounts(Decimal(item_discounts), Decimal(promotions)),
        fees=Fees(Decimal(delivery_fee), Decimal(service_fee), Decimal(pickup_fee)),
        pickup_point_name=pickup_name,
        pickup_area=pickup_area,
        pickup_window=window,
    )


class DeliveryProfileSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GROCERY_AGENT_MASTER_KEY"] = "unit-test-master-key-only"

    def test_owner_only_encrypted_delivery_profile_and_masked_surfaces(self) -> None:
        tmp = Path(__file__).resolve().parents[1] / ".test-tmp"
        tmp.mkdir(exist_ok=True)
        profile_path = tmp / "profile.enc"
        profile_path.unlink(missing_ok=True)
        store = DeliveryProfileStore(profile_path, EnvMasterKeyCryptoProvider.from_env())
        form = DeliveryProfileAdminForm(store)
        profile = form.submit(
            SHAY,
            DeliveryAddress(city="Pardesiya", address_line=SENSITIVE_TEST_ADDRESS, recipient_note="synthetic"),
        )

        encrypted_file = profile_path.read_text(encoding="utf-8")
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, encrypted_file)
        self.assertEqual(store.load().address.address_line, SENSITIVE_TEST_ADDRESS)
        self.assertEqual(profile.masked_display(), MASKED_DELIVERY_ADDRESS)

        api_response = profile_api_response(profile)
        audit_record = audit_delivery_profile_used(profile)
        email = profile_email_fragment(profile)
        url = f"https://app.local/profiles/{profile.id}?delivery_profile_id={profile.id}"

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("profile-test")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        RedactingLogger(logger).info_delivery_profile_used(profile.id)

        surfaces = json.dumps([api_response, audit_record, email, url, log_stream.getvalue()], ensure_ascii=False)
        self.assertNotIn(SENSITIVE_TEST_ADDRESS, surfaces)
        self.assertIn(MASKED_DELIVERY_ADDRESS, surfaces)
        self.assertEqual(audit_record, {"event": "delivery_profile_used", "delivery_profile_id": profile.id})

    def test_michal_can_use_but_not_edit_profile(self) -> None:
        self.assertTrue(can(SHAY, "edit_delivery_profile"))
        self.assertTrue(can(SHAY, "change_budget_threshold"))
        self.assertTrue(can(MICHAL, "submit_list"))
        self.assertTrue(can(MICHAL, "resolve_product_exceptions"))
        self.assertTrue(can(MICHAL, "choose_fulfillment"))
        self.assertTrue(can(MICHAL, "approve_budget_warning"))
        self.assertTrue(can(MICHAL, "approve_cart_preparation"))
        self.assertTrue(can(MICHAL, "use_delivery_profile"))
        self.assertFalse(can(MICHAL, "edit_delivery_profile"))
        self.assertFalse(can(MICHAL, "manage_allowlist"))


class PickupPolicyTests(unittest.TestCase):
    def test_pickup_shown_only_for_eligible_emek_hefer_pickup_points(self) -> None:
        delivery = order()
        eligible = PickupPoint("p1", "Pickup North", "Emek Hefer", Decimal("5"), (TimeWindow.parse("17:00", "18:00"),))
        wrong_area = PickupPoint("p2", "Other Area", "Sharon", Decimal("1"), (TimeWindow.parse("17:00", "18:00"),))

        pickups = eligible_pickup_estimates(delivery, (eligible, wrong_area))

        self.assertEqual(len(pickups), 1)
        self.assertEqual(pickups[0].pickup_point_name, "Pickup North")

    def test_pickup_requires_window_overlap_with_preference(self) -> None:
        delivery = order()
        early = PickupPoint("p1", "Early", "Emek Hefer", Decimal("0"), (TimeWindow.parse("14:00", "15:00"),))
        overlapping = PickupPoint("p2", "Overlap", "Emek Hefer", Decimal("0"), (TimeWindow.parse("18:00", "19:00"),))

        pickups = eligible_pickup_estimates(delivery, (early, overlapping), PickupPreference(TimeWindow.parse("16:30", "18:30")))

        self.assertEqual(len(pickups), 1)
        self.assertEqual(pickups[0].pickup_point_name, "Overlap")

    def test_unavailable_pickup_falls_back_to_delivery_comparison(self) -> None:
        unavailable = order(items=(item(available=False),))
        offer = RetailerOffer("Retailer A", delivery=unavailable, pickup_points=(PickupPoint("p1", "Pickup", "Emek Hefer", Decimal("0"), (TimeWindow.parse("17:00", "18:00"),)),))

        self.assertEqual(eligible_pickup_estimates(offer.delivery, offer.pickup_points), ())

        viable_delivery = RetailerOffer("Retailer B", delivery=order("Retailer B", "120"))
        rec = recommend((offer, viable_delivery))
        self.assertEqual(rec.strategy, "one_retailer_delivery")
        self.assertEqual(rec.orders[0].retailer, "Retailer B")

    def test_pickup_summary_contains_required_comparison_fields(self) -> None:
        delivery = order("Retailer A", "100", delivery_fee="20", service_fee="5", item_discounts="10")
        point = PickupPoint("p1", "Pickup North", "Emek Hefer", Decimal("3"), (TimeWindow.parse("17:00", "18:00"),))
        pickup = eligible_pickup_estimates(delivery, (point,))[0]
        summary = pickup_summary(pickup, delivery)

        self.assertEqual(summary["retailer"], "Retailer A")
        self.assertEqual(summary["pickup_point_name"], "Pickup North")
        self.assertEqual(summary["pickup_fee"], Decimal("3"))
        self.assertEqual(summary["final_basket_price_after_discounts"], Decimal("98.00"))
        self.assertEqual(summary["difference_versus_delivery"], Decimal("-17.00"))


class BudgetAndTotalsTests(unittest.TestCase):
    def test_pickup_and_delivery_totals_after_discounts_and_fees(self) -> None:
        delivery = order("Retailer A", "100", delivery_fee="20", service_fee="5", item_discounts="10", promotions="7")
        pickup = order("Retailer A", "100", mode=FulfillmentMode.PICKUP, pickup_fee="4", service_fee="5", item_discounts="10", promotions="7")

        self.assertEqual(delivery.final_total, Decimal("108.00"))
        self.assertEqual(pickup.final_total, Decimal("92.00"))

    def test_budget_warning_uses_post_discount_total(self) -> None:
        policy = BudgetPolicy()
        gross_over_discount_under = order("Retailer A", "850", item_discounts="60")
        net_over = order("Retailer A", "850", item_discounts="49.99")

        self.assertIsNone(policy.order_warning(gross_over_discount_under))
        self.assertEqual(policy.order_warning(net_over), BUDGET_ACK_TEXT_HE)

    def test_exactly_800_does_not_trigger_but_800_01_does(self) -> None:
        policy = BudgetPolicy()

        self.assertFalse(policy.requires_acknowledgement(Decimal("800.00")))
        self.assertTrue(policy.requires_acknowledgement(Decimal("800.01")))

    def test_weighted_product_notice_and_estimate(self) -> None:
        estimate = order(items=(weighted_item(),), delivery_fee="10")

        self.assertEqual(estimate.final_total, money("40.00"))
        self.assertIn("\u05d4\u05de\u05e9\u05e7\u05dc \u05d1\u05e4\u05d5\u05e2\u05dc", estimate.weight_notice_he())


class RecommendationTests(unittest.TestCase):
    def test_split_basket_requires_25_ils_saving_after_all_fees(self) -> None:
        full = (item("a", "50"), item("b", "50"))
        best_single = RetailerOffer("One", delivery=order("One", items=full))
        split_a_24 = order("A", items=(item("a", "38"),), delivery_fee="0")
        split_b_24 = order("B", items=(item("b", "38"),), delivery_fee="0")
        no_split = recommend((best_single,), split_candidates=((split_a_24, split_b_24),))
        self.assertNotEqual(no_split.strategy, "split_basket")

        split_a_25 = order("A", items=(item("a", "37.50"),), delivery_fee="0")
        split_b_25 = order("B", items=(item("b", "37.50"),), delivery_fee="0")
        split = recommend((best_single,), split_candidates=((split_a_25, split_b_25),))
        self.assertEqual(split.strategy, "split_basket")
        self.assertEqual(split.savings_ils, Decimal("25.00"))

    def test_two_pickup_journeys_blocked_unless_windows_overlap(self) -> None:
        full = (item("a", "60"), item("b", "60"))
        best_single = RetailerOffer("One", delivery=order("One", items=full, delivery_fee="20"))
        pickup_a = order(
            "A",
            mode=FulfillmentMode.PICKUP,
            items=(item("a", "40"),),
            pickup_name="Point A",
            pickup_area="Emek Hefer",
            window=TimeWindow.parse("16:30", "17:00"),
        )
        pickup_b_non_overlap = order(
            "B",
            mode=FulfillmentMode.PICKUP,
            items=(item("b", "40"),),
            pickup_name="Point B",
            pickup_area="Emek Hefer",
            window=TimeWindow.parse("18:00", "18:30"),
        )
        blocked = recommend((best_single,), split_candidates=((pickup_a, pickup_b_non_overlap),))
        self.assertEqual(blocked.strategy, "one_retailer_delivery")

        pickup_b_overlap = order(
            "B",
            mode=FulfillmentMode.PICKUP,
            items=(item("b", "40"),),
            pickup_name="Point B",
            pickup_area="Emek Hefer",
            window=TimeWindow.parse("16:45", "17:30"),
        )
        allowed = recommend((best_single,), split_candidates=((pickup_a, pickup_b_overlap),))
        self.assertEqual(allowed.strategy, "split_basket")



    def test_two_pickup_journeys_blocked_unless_locations_are_emek_hefer(self) -> None:
        full = (item("a", "60"), item("b", "60"))
        best_single = RetailerOffer("One", delivery=order("One", items=full, delivery_fee="20"))
        pickup_a = order(
            "A",
            mode=FulfillmentMode.PICKUP,
            items=(item("a", "40"),),
            pickup_name="Point A",
            pickup_area="Emek Hefer",
            window=TimeWindow.parse("16:30", "17:30"),
        )
        pickup_b_wrong_area = order(
            "B",
            mode=FulfillmentMode.PICKUP,
            items=(item("b", "40"),),
            pickup_name="Point B",
            pickup_area="Sharon",
            window=TimeWindow.parse("16:45", "17:15"),
        )

        blocked = recommend((best_single,), split_candidates=((pickup_a, pickup_b_wrong_area),))

        self.assertEqual(blocked.strategy, "one_retailer_delivery")

if __name__ == "__main__":
    unittest.main()








