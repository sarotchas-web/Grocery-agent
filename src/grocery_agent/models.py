from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable


ILS = Decimal


class FulfillmentMode(str, Enum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


class Role(str, Enum):
    OWNER = "OWNER"
    HOUSEHOLD_MEMBER = "HOUSEHOLD_MEMBER"


@dataclass(frozen=True)
class User:
    id: str
    display_name: str
    role: Role


@dataclass(frozen=True)
class BasketItem:
    sku: str
    name: str
    quantity: Decimal
    unit_price: Decimal
    available: bool = True
    weighted: bool = False
    estimated_weight_kg: Decimal | None = None

    @property
    def estimated_total(self) -> Decimal:
        if self.weighted and self.estimated_weight_kg is not None:
            return self.unit_price * self.estimated_weight_kg
        return self.unit_price * self.quantity


@dataclass(frozen=True)
class Fees:
    delivery: Decimal = Decimal("0")
    service: Decimal = Decimal("0")
    pickup: Decimal = Decimal("0")


@dataclass(frozen=True)
class Discounts:
    item_discounts: Decimal = Decimal("0")
    promotions: Decimal = Decimal("0")


@dataclass(frozen=True)
class OrderEstimate:
    retailer: str
    mode: FulfillmentMode
    items: tuple[BasketItem, ...]
    discounts: Discounts = field(default_factory=Discounts)
    fees: Fees = field(default_factory=Fees)
    pickup_point_name: str | None = None
    pickup_area: str | None = None
    pickup_window: "TimeWindow | None" = None

    @property
    def item_subtotal(self) -> Decimal:
        return money(sum((item.estimated_total for item in self.items), Decimal("0")))

    @property
    def final_total(self) -> Decimal:
        gross = self.item_subtotal
        discount_total = self.discounts.item_discounts + self.discounts.promotions
        fees_total = self.fees.delivery + self.fees.service + self.fees.pickup
        return money(max(Decimal("0"), gross - discount_total + fees_total))

    @property
    def has_weighted_items(self) -> bool:
        return any(item.weighted for item in self.items)

    @property
    def all_items_available(self) -> bool:
        return all(item.available for item in self.items)

    def weight_notice_he(self) -> str | None:
        if not self.has_weighted_items:
            return None
        return "\u05d4\u05e1\u05db\u05d5\u05dd \u05db\u05d5\u05dc\u05dc \u05d4\u05e2\u05e8\u05db\u05ea \u05de\u05e9\u05e7\u05dc; \u05d4\u05d7\u05d9\u05d5\u05d1 \u05d4\u05e1\u05d5\u05e4\u05d9 \u05e2\u05e9\u05d5\u05d9 \u05dc\u05d4\u05e9\u05ea\u05e0\u05d5\u05ea \u05dc\u05e4\u05d9 \u05d4\u05de\u05e9\u05e7\u05dc \u05d1\u05e4\u05d5\u05e2\u05dc."


@dataclass(frozen=True)
class TimeWindow:
    start_minutes: int
    end_minutes: int
    timezone: str = "Asia/Jerusalem"

    @classmethod
    def parse(cls, start: str, end: str, timezone: str = "Asia/Jerusalem") -> "TimeWindow":
        return cls(_to_minutes(start), _to_minutes(end), timezone)

    def overlaps(self, other: "TimeWindow") -> bool:
        return self.timezone == other.timezone and self.start_minutes < other.end_minutes and other.start_minutes < self.end_minutes

    def display(self) -> str:
        return f"{_from_minutes(self.start_minutes)}-{_from_minutes(self.end_minutes)} {self.timezone}"


@dataclass(frozen=True)
class PickupPoint:
    id: str
    name: str
    area: str
    fee: Decimal
    windows: tuple[TimeWindow, ...]


@dataclass(frozen=True)
class RetailerOffer:
    retailer: str
    delivery: OrderEstimate
    pickup_points: tuple[PickupPoint, ...] = ()


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def total_orders(orders: Iterable[OrderEstimate]) -> Decimal:
    return money(sum((order.final_total for order in orders), Decimal("0")))


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _from_minutes(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"




