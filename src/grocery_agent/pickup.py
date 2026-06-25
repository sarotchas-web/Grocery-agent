from __future__ import annotations

from dataclasses import dataclass

from grocery_agent.models import OrderEstimate, PickupPoint, TimeWindow, FulfillmentMode, Fees


EMEK_HEFER_AREA = "Emek Hefer"
DEFAULT_PICKUP_PREFERENCE = TimeWindow.parse("16:30", "18:30")


@dataclass(frozen=True)
class PickupPreference:
    preferred_window: TimeWindow = DEFAULT_PICKUP_PREFERENCE
    required_area: str = EMEK_HEFER_AREA


def eligible_pickup_estimates(
    delivery_estimate: OrderEstimate,
    pickup_points: tuple[PickupPoint, ...],
    preference: PickupPreference = PickupPreference(),
) -> tuple[OrderEstimate, ...]:
    if not delivery_estimate.all_items_available:
        return ()
    eligible: list[OrderEstimate] = []
    for point in pickup_points:
        if point.area != preference.required_area:
            continue
        for window in point.windows:
            if not window.overlaps(preference.preferred_window):
                continue
            eligible.append(
                OrderEstimate(
                    retailer=delivery_estimate.retailer,
                    mode=FulfillmentMode.PICKUP,
                    items=delivery_estimate.items,
                    discounts=delivery_estimate.discounts,
                    fees=Fees(service=delivery_estimate.fees.service, pickup=point.fee),
                    pickup_point_name=point.name,
                    pickup_area=point.area,
                    pickup_window=window,
                )
            )
    return tuple(eligible)


def pickup_summary(pickup: OrderEstimate, delivery: OrderEstimate) -> dict:
    if pickup.mode != FulfillmentMode.PICKUP:
        raise ValueError("pickup_summary requires a pickup estimate")
    return {
        "retailer": pickup.retailer,
        "pickup_point_name": pickup.pickup_point_name,
        "pickup_window": pickup.pickup_window.display() if pickup.pickup_window else None,
        "pickup_fee": pickup.fees.pickup,
        "final_basket_price_after_discounts": pickup.final_total,
        "difference_versus_delivery": pickup.final_total - delivery.final_total,
    }



