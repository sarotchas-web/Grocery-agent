from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from grocery_agent.models import OrderEstimate, money, total_orders


DEFAULT_BUDGET_THRESHOLD_ILS = Decimal("800.00")
BUDGET_ACK_TEXT_HE = "\u05d0\u05e0\u05d9 \u05de\u05d0\u05e9\u05e8/\u05ea \u05d7\u05e8\u05d9\u05d2\u05d4 \u05de\u05e2\u05dc \u20aa800"


@dataclass(frozen=True)
class BudgetPolicy:
    threshold_ils: Decimal = DEFAULT_BUDGET_THRESHOLD_ILS

    def requires_acknowledgement(self, final_estimated_amount: Decimal) -> bool:
        return money(final_estimated_amount) > money(self.threshold_ils)

    def order_warning(self, order: OrderEstimate) -> str | None:
        if not self.requires_acknowledgement(order.final_total):
            return None
        return BUDGET_ACK_TEXT_HE

    def split_warnings(self, orders: tuple[OrderEstimate, ...]) -> list[str]:
        warnings: list[str] = []
        for order in orders:
            warning = self.order_warning(order)
            if warning is not None:
                warnings.append(warning)
        if self.requires_acknowledgement(total_orders(orders)):
            warnings.append(BUDGET_ACK_TEXT_HE)
        return warnings

