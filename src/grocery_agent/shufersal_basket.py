from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from grocery_agent.models import money
from grocery_agent.shufersal_promotions import ShufersalProductOffer


@dataclass(frozen=True)
class ShufersalBasketLine:
    offer: ShufersalProductOffer
    quantity: Decimal

    @property
    def regular_total_ils(self) -> Decimal:
        return money(self.offer.product.price_ils * self.quantity)

    @property
    def estimated_total_ils(self) -> Decimal:
        return money(self.offer.effective_price_ils * self.quantity)


@dataclass(frozen=True)
class ShufersalBasket:
    lines: tuple[ShufersalBasketLine, ...] = ()

    @property
    def regular_total_ils(self) -> Decimal:
        return money(sum((line.regular_total_ils for line in self.lines), Decimal("0")))

    @property
    def estimated_total_ils(self) -> Decimal:
        return money(sum((line.estimated_total_ils for line in self.lines), Decimal("0")))

    @property
    def public_savings_ils(self) -> Decimal:
        return money(self.regular_total_ils - self.estimated_total_ils)

    @property
    def has_weighted_items(self) -> bool:
        return any(line.offer.product.weighted for line in self.lines)

    @property
    def shopping_list_text(self) -> str:
        return "\n".join(
            f"{line.offer.product.name} x {line.quantity:g}"
            for line in self.lines
        )


class ShufersalBasketStore:
    """Process-local basket selection with no credentials or checkout data."""

    def __init__(self) -> None:
        self._lines_by_actor: dict[str, dict[str, ShufersalBasketLine]] = {}
        self._lock = threading.Lock()

    def get(self, actor_id: str) -> ShufersalBasket:
        with self._lock:
            lines = self._lines_by_actor.get(actor_id, {})
            return ShufersalBasket(tuple(lines.values()))

    def add(
        self,
        actor_id: str,
        offer: ShufersalProductOffer,
        quantity: Decimal | str,
    ) -> ShufersalBasket:
        parsed_quantity = _quantity(quantity)
        with self._lock:
            lines = self._lines_by_actor.setdefault(actor_id, {})
            existing = lines.get(offer.product.item_code)
            combined = parsed_quantity + (existing.quantity if existing else Decimal("0"))
            if combined > Decimal("100"):
                raise ValueError("\u05d4\u05db\u05de\u05d5\u05ea \u05d4\u05de\u05e8\u05d1\u05d9\u05ea \u05dc\u05de\u05d5\u05e6\u05e8 \u05d4\u05d9\u05d0 100.")
            lines[offer.product.item_code] = ShufersalBasketLine(offer, combined)
            return ShufersalBasket(tuple(lines.values()))

    def remove(self, actor_id: str, item_code: str) -> ShufersalBasket:
        with self._lock:
            lines = self._lines_by_actor.get(actor_id, {})
            lines.pop(item_code, None)
            return ShufersalBasket(tuple(lines.values()))

    def clear(self, actor_id: str) -> ShufersalBasket:
        with self._lock:
            self._lines_by_actor.pop(actor_id, None)
            return ShufersalBasket()


def _quantity(value: Decimal | str) -> Decimal:
    try:
        quantity = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("\u05d9\u05e9 \u05dc\u05d4\u05d6\u05d9\u05df \u05db\u05de\u05d5\u05ea \u05ea\u05e7\u05d9\u05e0\u05d4.") from exc
    if quantity <= 0 or quantity > Decimal("100"):
        raise ValueError("\u05d4\u05db\u05de\u05d5\u05ea \u05d7\u05d9\u05d9\u05d1\u05ea \u05dc\u05d4\u05d9\u05d5\u05ea \u05d1\u05d9\u05df 0 \u05dc\u05be100.")
    return quantity
