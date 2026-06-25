from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from grocery_agent.models import BasketItem, FulfillmentMode, OrderEstimate, RetailerOffer, total_orders
from grocery_agent.pickup import PickupPreference, eligible_pickup_estimates


SPLIT_MINIMUM_SAVINGS_ILS = Decimal("25.00")


@dataclass(frozen=True)
class Recommendation:
    strategy: str
    orders: tuple[OrderEstimate, ...]
    explanation_he: str
    savings_ils: Decimal = Decimal("0.00")


def recommend(
    offers: tuple[RetailerOffer, ...],
    preference: PickupPreference = PickupPreference(),
    split_candidates: tuple[tuple[OrderEstimate, OrderEstimate], ...] = (),
) -> Recommendation:
    delivery_candidates = tuple(offer.delivery for offer in offers if offer.delivery.all_items_available)
    if not delivery_candidates:
        raise ValueError("No viable delivery offers")

    single_delivery = min(delivery_candidates, key=lambda order: order.final_total)
    pickup_candidates = []
    for offer in offers:
        pickup_candidates.extend(eligible_pickup_estimates(offer.delivery, offer.pickup_points, preference))
    single_candidates = delivery_candidates + tuple(pickup_candidates)
    best_single = min(single_candidates, key=_score_single)

    split = _best_split(delivery_candidates, tuple(pickup_candidates), best_single, split_candidates)
    if split is not None:
        return split

    if best_single.mode == FulfillmentMode.PICKUP:
        return Recommendation(
            strategy="one_retailer_pickup",
            orders=(best_single,),
            explanation_he="נבחר איסוף כי הוא זמין בפועל, עומד באזור ובחלון המועדף, וכל הפריטים זמינים; הוא קיבל ציון טוב יותר ממשלוח לפי מחיר, זמינות ותזמון.",
        )
    return Recommendation(
        strategy="one_retailer_delivery",
        orders=(best_single,),
        explanation_he="נבחר משלוח מקמעונאי אחד לאחר השוואת כל אפשרויות המשלוח והאיסוף הזמינות; זו האפשרות המתאימה ביותר לפי מחיר סופי, זמינות ותזמון.",
    )


def _score_single(order: OrderEstimate) -> tuple[Decimal, int]:
    timing_penalty = Decimal("0.00") if order.mode == FulfillmentMode.DELIVERY else Decimal("2.00")
    return (order.final_total + timing_penalty, 0 if order.all_items_available else 1)


def _best_split(
    delivery_candidates: tuple[OrderEstimate, ...],
    pickup_candidates: tuple[OrderEstimate, ...],
    best_single: OrderEstimate,
    split_candidates: tuple[tuple[OrderEstimate, OrderEstimate], ...],
) -> Recommendation | None:
    all_viable = split_candidates or _infer_split_candidates(delivery_candidates + pickup_candidates, best_single.items)
    if not all_viable:
        return None
    best_pair: tuple[OrderEstimate, OrderEstimate] | None = None
    best_total: Decimal | None = None
    for pair in all_viable:
        if pair[0].retailer == pair[1].retailer:
            continue
        if not _split_methods_viable(pair):
            continue
        if not _pickup_journeys_compatible(pair):
            continue
        total = total_orders(pair)
        if best_total is None or total < best_total:
            best_total = total
            best_pair = pair
    if best_pair is None or best_total is None:
        return None
    savings = best_single.final_total - best_total
    if savings < SPLIT_MINIMUM_SAVINGS_ILS:
        return None
    return Recommendation(
        strategy="split_basket",
        orders=best_pair,
        explanation_he="נבחר פיצול סל כי שני המסלולים ישימים, וכל העמלות נכללו במחיר הסופי; החיסכון הכולל לאחר עמלות הוא לפחות ₪25.",
        savings_ils=savings,
    )


def _split_methods_viable(orders: tuple[OrderEstimate, OrderEstimate]) -> bool:
    return all(order.all_items_available for order in orders)


def _pickup_journeys_compatible(orders: tuple[OrderEstimate, OrderEstimate]) -> bool:
    pickups = [order for order in orders if order.mode == FulfillmentMode.PICKUP]
    if len(pickups) < 2:
        return True
    first, second = pickups
    if first.pickup_window is None or second.pickup_window is None:
        return False
    if first.pickup_area != "Emek Hefer" or second.pickup_area != "Emek Hefer":
        return False
    return first.pickup_window.overlaps(second.pickup_window)


def _infer_split_candidates(
    orders: tuple[OrderEstimate, ...],
    full_basket: tuple[BasketItem, ...],
) -> tuple[tuple[OrderEstimate, OrderEstimate], ...]:
    candidates: list[tuple[OrderEstimate, OrderEstimate]] = []
    sku_set = {item.sku for item in full_basket}
    for left in orders:
        for right in orders:
            if left.retailer == right.retailer:
                continue
            combined = {item.sku for item in left.items} | {item.sku for item in right.items}
            overlap = {item.sku for item in left.items} & {item.sku for item in right.items}
            if combined == sku_set and not overlap:
                candidates.append((left, right))
    return tuple(candidates)



