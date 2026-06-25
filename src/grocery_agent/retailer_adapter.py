from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from grocery_agent.models import OrderEstimate, PickupPoint
from grocery_agent.pickup import PickupPreference, eligible_pickup_estimates


class RetailerAdapter(Protocol):
    """Runtime boundary for retailer-specific availability, price, delivery and pickup data."""

    def quote_delivery(self, basket_id: str, delivery_profile_id: str) -> OrderEstimate:
        """Return a delivery estimate without exposing the decrypted address."""

    def list_pickup_points(self, basket_id: str) -> tuple[PickupPoint, ...]:
        """Return current pickup points and collection windows from the retailer."""


@dataclass(frozen=True)
class RetailerComparison:
    delivery: OrderEstimate
    eligible_pickups: tuple[OrderEstimate, ...]


def compare_retailer(
    adapter: RetailerAdapter,
    basket_id: str,
    delivery_profile_id: str,
    preference: PickupPreference = PickupPreference(),
) -> RetailerComparison:
    delivery = adapter.quote_delivery(basket_id=basket_id, delivery_profile_id=delivery_profile_id)
    pickup_points = adapter.list_pickup_points(basket_id=basket_id)
    return RetailerComparison(
        delivery=delivery,
        eligible_pickups=eligible_pickup_estimates(delivery, pickup_points, preference),
    )
