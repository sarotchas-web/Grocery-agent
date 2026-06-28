from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape

from grocery_agent.budget import BUDGET_ACK_TEXT_HE, BudgetPolicy
from grocery_agent.models import (
    BasketItem,
    Discounts,
    Fees,
    FulfillmentMode,
    OrderEstimate,
    PickupPoint,
    RetailerOffer,
    TimeWindow,
    money,
)
from grocery_agent.pickup import PickupPreference, eligible_pickup_estimates, pickup_summary
from grocery_agent.recommendation import Recommendation, recommend


@dataclass(frozen=True)
class OrderComparison:
    items: tuple[str, ...]
    offers: tuple[RetailerOffer, ...]
    recommendation: Recommendation


def parse_shopping_list(raw: str) -> tuple[str, ...]:
    items = tuple(line.strip() for line in raw.splitlines() if line.strip())
    if not items:
        raise ValueError("\u05d9\u05e9 \u05dc\u05d4\u05d5\u05e1\u05d9\u05e3 \u05dc\u05e4\u05d7\u05d5\u05ea \u05de\u05d5\u05e6\u05e8 \u05d0\u05d7\u05d3.")
    return items


def compare_order_form(form: dict[str, str]) -> OrderComparison:
    items = parse_shopping_list(form.get("items", ""))
    offers = tuple(
        offer
        for prefix in ("a", "b")
        if (offer := _offer_from_form(prefix, form)) is not None
    )
    if not offers:
        raise ValueError("\u05d9\u05e9 \u05dc\u05d4\u05d5\u05e1\u05d9\u05e3 \u05d4\u05e6\u05e2\u05d4 \u05e9\u05dc \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 \u05d0\u05d7\u05d3 \u05dc\u05e4\u05d7\u05d5\u05ea.")
    try:
        recommendation = recommend(offers)
    except ValueError as exc:
        raise ValueError("\u05dc\u05e4\u05d7\u05d5\u05ea \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 \u05d0\u05d7\u05d3 \u05d7\u05d9\u05d9\u05d1 \u05dc\u05d4\u05e6\u05d9\u05e2 \u05d0\u05ea \u05db\u05dc \u05d4\u05e1\u05dc \u05d1\u05de\u05e9\u05dc\u05d5\u05d7.") from exc
    return OrderComparison(items=items, offers=offers, recommendation=recommendation)


def render_new_order_form(actor_id: str) -> str:
    return f"""
    <section class="toolbar">
      <a href="/?actor={escape(actor_id)}">\u05d7\u05d6\u05e8\u05d4</a>
    </section>
    <section class="band">
      <p class="eyebrow">\u05d4\u05d6\u05de\u05e0\u05d4 \u05d7\u05d3\u05e9\u05d4</p>
      <h1>\u05d1\u05e0\u05d9\u05d9\u05ea \u05e8\u05e9\u05d9\u05de\u05ea \u05d4\u05e7\u05e0\u05d9\u05d5\u05ea</h1>
      <p class="muted">\u05d4\u05e8\u05e9\u05d9\u05de\u05d4 \u05e0\u05e9\u05d0\u05e8\u05ea \u05d1\u05de\u05d7\u05e9\u05d1 \u05d6\u05d4 \u05d5\u05d0\u05d9\u05e0\u05d4 \u05e0\u05e9\u05dc\u05d7\u05ea \u05dc\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9.</p>
    </section>
    <form method="post" action="/orders/quotes" class="form order-form">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <label>\u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05dc\u05e7\u05e0\u05d9\u05d9\u05d4
        <textarea name="items" rows="10" required placeholder="\u05d7\u05dc\u05d1&#10;\u05dc\u05d7\u05dd&#10;\u05ea\u05e4\u05d5\u05d7\u05d9\u05dd"></textarea>
      </label>
      <button type="submit">\u05d4\u05de\u05e9\u05da \u05dc\u05d4\u05e6\u05e2\u05d5\u05ea \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9\u05dd</button>
    </form>
    """


def render_quote_form(actor_id: str, items_raw: str) -> str:
    items = parse_shopping_list(items_raw)
    item_rows = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"""
    <section class="toolbar">
      <a href="/orders/new?actor={escape(actor_id)}">\u05d7\u05d6\u05e8\u05d4</a>
    </section>
    <section class="band">
      <p class="eyebrow">\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9\u05dd</p>
      <h1>\u05d4\u05d5\u05e1\u05e4\u05ea \u05d4\u05e6\u05e2\u05d5\u05ea \u05e1\u05dc \u05e2\u05d3\u05db\u05e0\u05d9\u05d5\u05ea</h1>
      <p class="muted">\u05d9\u05e9 \u05dc\u05d4\u05d6\u05d9\u05df \u05e0\u05ea\u05d5\u05e0\u05d9\u05dd \u05e2\u05d3\u05db\u05e0\u05d9\u05d9\u05dd \u05de\u05db\u05dc \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9. \u05d0\u05d9\u05df \u05d7\u05d9\u05d1\u05d5\u05e8 \u05dc\u05d7\u05e9\u05d1\u05d5\u05df \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9.</p>
      <ul class="compact-list">{item_rows}</ul>
    </section>
    <form method="post" action="/orders/recommend" class="quote-form">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <textarea name="items" hidden>{escape(items_raw)}</textarea>
      {_retailer_fields("a", "\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 1")}
      {_retailer_fields("b", "\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 2", required=False)}
      <div class="form-actions">
        <button type="submit">\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05d0\u05e4\u05e9\u05e8\u05d5\u05d9\u05d5\u05ea</button>
      </div>
    </form>
    """


def render_comparison(actor_id: str, comparison: OrderComparison) -> str:
    alternatives: list[str] = []
    for offer in comparison.offers:
        alternatives.append(_estimate_row(offer.delivery))
        for pickup in eligible_pickup_estimates(offer.delivery, offer.pickup_points, PickupPreference()):
            summary = pickup_summary(pickup, offer.delivery)
            alternatives.append(
                f"""
                <tr>
                  <td>{escape(str(summary["retailer"]))}</td>
                  <td>\u05d0\u05d9\u05e1\u05d5\u05e3</td>
                  <td>{escape(str(summary["pickup_point_name"]))}</td>
                  <td>{escape(_window_title(str(summary["pickup_window"])))}</td>
                  <td>\u20aa{summary["pickup_fee"]}</td>
                  <td>\u20aa{summary["final_basket_price_after_discounts"]}</td>
                  <td>\u20aa{summary["difference_versus_delivery"]}</td>
                </tr>
                """
            )

    recommendation = comparison.recommendation
    total = money(sum((order.final_total for order in recommendation.orders), Decimal("0")))
    policy = BudgetPolicy()
    acknowledgement_required = policy.requires_acknowledgement(total)
    acknowledgement = (
        f'<label class="ack"><input type="checkbox" name="budget_ack" value="yes" required> '
        f'{escape(BUDGET_ACK_TEXT_HE)}</label>'
        if acknowledgement_required
        else '<p class="ok">\u05d0\u05d9\u05df \u05e6\u05d5\u05e8\u05da \u05d1\u05d0\u05d9\u05e9\u05d5\u05e8 \u05ea\u05e7\u05e6\u05d9\u05d1.</p>'
    )
    weighted_notice = next(
        (order.weight_notice_he() for order in recommendation.orders if order.weight_notice_he()),
        None,
    )
    recommended_rows = "".join(
        f"<li><strong>{escape(order.retailer)}</strong> | {_mode_title(order.mode)} | \u20aa{order.final_total}</li>"
        for order in recommendation.orders
    )
    return f"""
    <section class="toolbar">
      <a href="/orders/new?actor={escape(actor_id)}">\u05d4\u05ea\u05d7\u05dc\u05d4 \u05de\u05d7\u05d3\u05e9</a>
    </section>
    <section class="band recommendation">
      <p class="eyebrow">\u05d4\u05de\u05dc\u05e6\u05d4</p>
      <h1>{escape(_strategy_title(recommendation.strategy))}</h1>
      <p lang="he" dir="rtl">{escape(recommendation.explanation_he)}</p>
      <ul class="compact-list">{recommended_rows}</ul>
      <p class="total">\u05e1\u05db\u05d5\u05dd \u05de\u05e9\u05d5\u05e2\u05e8 <strong>\u20aa{total}</strong></p>
      {f'<p class="warning" lang="he" dir="rtl">{escape(weighted_notice)}</p>' if weighted_notice else ''}
    </section>
    <section class="table-band">
      <h2>\u05d0\u05e4\u05e9\u05e8\u05d5\u05d9\u05d5\u05ea \u05e9\u05d4\u05d5\u05e9\u05d5\u05d5</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9</th><th>\u05e9\u05d9\u05d8\u05d4</th><th>\u05e0\u05e7\u05d5\u05d3\u05ea \u05d0\u05d9\u05e1\u05d5\u05e3</th><th>\u05d7\u05dc\u05d5\u05df</th><th>\u05d3\u05de\u05d9 \u05d0\u05d9\u05e1\u05d5\u05e3</th><th>\u05e1\u05db\u05d5\u05dd \u05e1\u05d5\u05e4\u05d9</th><th>\u05d4\u05e4\u05e8\u05e9 \u05de\u05de\u05e9\u05dc\u05d5\u05d7</th></tr></thead>
          <tbody>{''.join(alternatives)}</tbody>
        </table>
      </div>
    </section>
    <form method="post" action="/orders/approve" class="form approval-form">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <input type="hidden" name="estimated_total" value="{total}">
      <input type="hidden" name="strategy" value="{escape(recommendation.strategy)}">
      {acknowledgement}
      <button type="submit">\u05d0\u05d9\u05e9\u05d5\u05e8 \u05d4\u05db\u05e0\u05ea \u05d4\u05e1\u05dc</button>
    </form>
    """


def render_approval(form: dict[str, str]) -> str:
    total = _decimal(form.get("estimated_total", ""), "\u05e1\u05db\u05d5\u05dd \u05de\u05e9\u05d5\u05e2\u05e8")
    if BudgetPolicy().requires_acknowledgement(total) and form.get("budget_ack") != "yes":
        raise PermissionError(BUDGET_ACK_TEXT_HE)
    return f"""
    <section class="toolbar"><a href="/">\u05d3\u05e3 \u05d4\u05d1\u05d9\u05ea</a></section>
    <section class="band success">
      <p class="eyebrow">\u05d4\u05db\u05e0\u05ea \u05d4\u05e1\u05dc</p>
      <h1>\u05d0\u05d5\u05e9\u05e8</h1>
      <p>\u05d0\u05e1\u05d8\u05e8\u05d8\u05d2\u05d9\u05d4: <strong>{escape(_strategy_title(form.get("strategy", "")))}</strong></p>
      <p class="total">\u05e1\u05db\u05d5\u05dd \u05de\u05e9\u05d5\u05e2\u05e8 <strong>\u20aa{total}</strong></p>
      <p class="muted">\u05dc\u05d0 \u05d1\u05d5\u05e6\u05e2\u05d5 \u05e8\u05db\u05d9\u05e9\u05d4, \u05ea\u05e9\u05dc\u05d5\u05dd \u05d0\u05d5 \u05d9\u05e6\u05d9\u05d0\u05d4 \u05dc\u05e7\u05d5\u05e4\u05d4 \u05d0\u05e6\u05dc \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9.</p>
    </section>
    """


def _offer_from_form(prefix: str, form: dict[str, str]) -> RetailerOffer | None:
    retailer = form.get(f"{prefix}_retailer", "").strip()
    if not retailer:
        return None
    available = form.get(f"{prefix}_available") == "yes"
    subtotal = _decimal(form.get(f"{prefix}_subtotal", ""), f"\u05e1\u05db\u05d5\u05dd \u05d1\u05d9\u05e0\u05d9\u05d9\u05dd \u05e2\u05d1\u05d5\u05e8 {retailer}")
    basket = (
        BasketItem(
            sku=f"{prefix}-basket",
            name="\u05e1\u05dc \u05de\u05dc\u05d0",
            quantity=Decimal("1"),
            unit_price=subtotal,
            available=available,
            weighted=form.get(f"{prefix}_weighted") == "yes",
            estimated_weight_kg=Decimal("1") if form.get(f"{prefix}_weighted") == "yes" else None,
        ),
    )
    delivery = OrderEstimate(
        retailer=retailer,
        mode=FulfillmentMode.DELIVERY,
        items=basket,
        discounts=Discounts(
            item_discounts=_optional_decimal(form.get(f"{prefix}_discounts")),
            promotions=_optional_decimal(form.get(f"{prefix}_promotions")),
        ),
        fees=Fees(
            delivery=_optional_decimal(form.get(f"{prefix}_delivery_fee")),
            service=_optional_decimal(form.get(f"{prefix}_service_fee")),
        ),
    )
    pickup_points: tuple[PickupPoint, ...] = ()
    if form.get(f"{prefix}_pickup") == "yes":
        point_name = form.get(f"{prefix}_pickup_name", "").strip()
        start = form.get(f"{prefix}_pickup_start", "").strip()
        end = form.get(f"{prefix}_pickup_end", "").strip()
        if not point_name or not start or not end:
            raise ValueError(f"\u05d9\u05e9 \u05dc\u05d4\u05e9\u05dc\u05d9\u05dd \u05d0\u05ea \u05e4\u05e8\u05d8\u05d9 \u05d4\u05d0\u05d9\u05e1\u05d5\u05e3 \u05e2\u05d1\u05d5\u05e8 {retailer}.")
        pickup_points = (
            PickupPoint(
                id=f"{prefix}-manual-pickup",
                name=point_name,
                area=form.get(f"{prefix}_pickup_area", "").strip(),
                fee=_optional_decimal(form.get(f"{prefix}_pickup_fee")),
                windows=(TimeWindow.parse(start, end),),
            ),
        )
    return RetailerOffer(retailer=retailer, delivery=delivery, pickup_points=pickup_points)


def _retailer_fields(prefix: str, title: str, required: bool = True) -> str:
    required_attr = "required" if required else ""
    return f"""
    <fieldset>
      <legend>{escape(title)}</legend>
      <div class="fields">
        <label>\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 <input name="{prefix}_retailer" {required_attr}></label>
        <label>\u05e1\u05db\u05d5\u05dd \u05d4\u05de\u05d5\u05e6\u05e8\u05d9\u05dd (\u05e9\u05f4\u05d7) <input name="{prefix}_subtotal" type="number" min="0" step="0.01" {required_attr}></label>
        <label>\u05d4\u05e0\u05d7\u05d5\u05ea \u05e2\u05dc \u05de\u05d5\u05e6\u05e8\u05d9\u05dd <input name="{prefix}_discounts" type="number" min="0" step="0.01" value="0"></label>
        <label>\u05de\u05d1\u05e6\u05e2\u05d9\u05dd <input name="{prefix}_promotions" type="number" min="0" step="0.01" value="0"></label>
        <label>\u05d3\u05de\u05d9 \u05de\u05e9\u05dc\u05d5\u05d7 <input name="{prefix}_delivery_fee" type="number" min="0" step="0.01" value="0"></label>
        <label>\u05d3\u05de\u05d9 \u05e9\u05d9\u05e8\u05d5\u05ea <input name="{prefix}_service_fee" type="number" min="0" step="0.01" value="0"></label>
      </div>
      <div class="checks">
        <label><input type="checkbox" name="{prefix}_available" value="yes" checked> \u05db\u05dc \u05d4\u05e1\u05dc \u05d6\u05de\u05d9\u05df</label>
        <label><input type="checkbox" name="{prefix}_weighted" value="yes"> \u05db\u05d5\u05dc\u05dc \u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05d1\u05de\u05e9\u05e7\u05dc</label>
        <label><input type="checkbox" name="{prefix}_pickup" value="yes"> \u05d4\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 \u05de\u05e6\u05d9\u05e2 \u05d0\u05d9\u05e1\u05d5\u05e3</label>
      </div>
      <div class="fields pickup-fields">
        <label>\u05e0\u05e7\u05d5\u05d3\u05ea \u05d0\u05d9\u05e1\u05d5\u05e3 <input name="{prefix}_pickup_name"></label>
        <label>\u05d0\u05d6\u05d5\u05e8 <select name="{prefix}_pickup_area"><option value="">\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d7\u05e8 \u05d0\u05d5 \u05dc\u05d0 \u05d9\u05d3\u05d5\u05e2</option><option value="Emek Hefer">\u05e2\u05de\u05e7 \u05d7\u05e4\u05e8</option></select></label>
        <label>\u05ea\u05d7\u05d9\u05dc\u05ea \u05d4\u05d7\u05dc\u05d5\u05df <input name="{prefix}_pickup_start" type="time"></label>
        <label>\u05e1\u05d9\u05d5\u05dd \u05d4\u05d7\u05dc\u05d5\u05df <input name="{prefix}_pickup_end" type="time"></label>
        <label>\u05d3\u05de\u05d9 \u05d0\u05d9\u05e1\u05d5\u05e3 <input name="{prefix}_pickup_fee" type="number" min="0" step="0.01" value="0"></label>
      </div>
    </fieldset>
    """


def _estimate_row(order: OrderEstimate) -> str:
    return f"""
    <tr>
      <td>{escape(order.retailer)}</td>
      <td>\u05de\u05e9\u05dc\u05d5\u05d7</td>
      <td>-</td><td>-</td><td>-</td>
      <td>\u20aa{order.final_total}</td>
      <td>-</td>
    </tr>
    """


def _mode_title(mode: FulfillmentMode) -> str:
    return "\u05de\u05e9\u05dc\u05d5\u05d7" if mode == FulfillmentMode.DELIVERY else "\u05d0\u05d9\u05e1\u05d5\u05e3"


def _window_title(value: str) -> str:
    return value.replace("-", "\u2013").replace("Asia/Jerusalem", "\u05e9\u05e2\u05d5\u05df \u05d9\u05e9\u05e8\u05d0\u05dc")


def _strategy_title(strategy: str) -> str:
    return {
        "one_retailer_delivery": "\u05de\u05e9\u05dc\u05d5\u05d7 \u05de\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 \u05d0\u05d7\u05d3",
        "one_retailer_pickup": "\u05d0\u05d9\u05e1\u05d5\u05e3 \u05de\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9 \u05d0\u05d7\u05d3",
        "split_basket": "\u05e4\u05d9\u05e6\u05d5\u05dc \u05d4\u05e1\u05dc",
    }.get(strategy, strategy)


def _optional_decimal(value: str | None) -> Decimal:
    if value is None or not value.strip():
        return Decimal("0")
    return _decimal(value, "\u05e1\u05db\u05d5\u05dd")


def _decimal(value: str, label: str) -> Decimal:
    try:
        amount = money(Decimal(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"\u05d9\u05e9 \u05dc\u05d4\u05d6\u05d9\u05df {label} \u05ea\u05e7\u05d9\u05df.") from exc
    if amount < 0:
        raise ValueError(f"{label} \u05d0\u05d9\u05e0\u05d5 \u05d9\u05db\u05d5\u05dc \u05dc\u05d4\u05d9\u05d5\u05ea \u05e9\u05dc\u05d9\u05dc\u05d9.")
    return amount
