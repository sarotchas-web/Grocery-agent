from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from grocery_agent.budget import BUDGET_ACK_TEXT_HE, BudgetPolicy
from grocery_agent.crypto import CryptoError, EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import (
    DeliveryAddress,
    DeliveryProfileAdminForm,
    DeliveryProfileStore,
    MASKED_DELIVERY_ADDRESS,
    profile_api_response,
)
from grocery_agent.models import Role, User, money
from grocery_agent.order_portal import (
    RetailerQuotePrefill,
    compare_order_form,
    parse_shopping_list,
    render_approval,
    render_comparison,
    render_new_order_form,
    render_quote_form,
)
from grocery_agent.permissions import can, require_permission
from grocery_agent.shufersal_adapter import ShufersalFeedError
from grocery_agent.shufersal_basket import ShufersalBasket, ShufersalBasketStore
from grocery_agent.shufersal_promotions import (
    ShufersalConnectionStatus,
    ShufersalProductOffer,
    ShufersalPublicOfferClient,
)


DEFAULT_PROFILE_PATH = Path(".local") / "delivery-profile.enc"


def run(host: str = "127.0.0.1", port: int = 8765, profile_path: Path = DEFAULT_PROFILE_PATH) -> None:
    handler = build_handler(profile_path)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"\u05e4\u05d5\u05e8\u05d8\u05dc \u05e1\u05d5\u05db\u05df \u05d4\u05e7\u05e0\u05d9\u05d5\u05ea: http://{host}:{port}")
    server.serve_forever()


def build_handler(
    profile_path: Path,
    shufersal_client: ShufersalPublicOfferClient | None = None,
) -> type[BaseHTTPRequestHandler]:
    offer_client = shufersal_client or ShufersalPublicOfferClient()
    basket_store = ShufersalBasketStore()

    class GroceryAgentHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = urlparse(self.path)
            actor = _actor(parse_qs(route.query).get("actor", ["michal"])[0])
            if route.path == "/":
                self._send_html(render_home(actor, _store(profile_path)))
                return
            if route.path == "/admin/profile":
                self._send_html(render_profile_form(actor))
                return
            if route.path == "/retailers/shufersal":
                require_permission(actor, "submit_list")
                self._send_html(_page("\u05de\u05d7\u05d9\u05e8\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc", render_shufersal_search(actor.id)))
                return
            if route.path == "/retailers/shufersal/basket":
                require_permission(actor, "submit_list")
                self._send_html(
                    _page(
                        "\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc",
                        render_shufersal_basket(actor.id, basket_store.get(actor.id)),
                    )
                )
                return
            if route.path == "/retailers/shufersal/basket/compare":
                require_permission(actor, "submit_list")
                basket = basket_store.get(actor.id)
                if not basket.lines:
                    self._send_html(render_error("\u05d9\u05e9 \u05dc\u05d4\u05d5\u05e1\u05d9\u05e3 \u05dc\u05e4\u05d7\u05d5\u05ea \u05de\u05d5\u05e6\u05e8 \u05d0\u05d7\u05d3 \u05dc\u05e1\u05dc."), status=400)
                    return
                self._send_html(
                    _page(
                        "\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05d4\u05d6\u05de\u05e0\u05d4",
                        render_shufersal_basket_quote(actor.id, basket),
                    )
                )
                return
            if route.path == "/retailers/shufersal/status":
                require_permission(actor, "submit_list")
                try:
                    status = offer_client.status()
                except ShufersalFeedError as exc:
                    self._send_html(render_error(str(exc)), status=502)
                    return
                self._send_html(
                    _page(
                        "\u05de\u05e6\u05d1 \u05d7\u05d9\u05d1\u05d5\u05e8 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc",
                        render_shufersal_status(actor.id, status),
                    )
                )
                return
            if route.path == "/orders/new":
                require_permission(actor, "submit_list")
                self._send_html(_page("\u05d4\u05d6\u05de\u05e0\u05d4 \u05d7\u05d3\u05e9\u05d4", render_new_order_form(actor.id)))
                return
            self._send_html(render_error("\u05d4\u05e2\u05de\u05d5\u05d3 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0."), status=404)

        def do_POST(self) -> None:
            route = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            form = {key: values[0] for key, values in parse_qs(body).items()}
            actor = _actor(form.get("actor", "michal"))
            try:
                if route.path == "/retailers/shufersal":
                    require_permission(actor, "submit_list")
                    query = form.get("query", "").strip()
                    offers = offer_client.search(query)
                    html = _page("\u05de\u05d7\u05d9\u05e8\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc", render_shufersal_search(actor.id, query, offers))
                elif route.path == "/retailers/shufersal/basket/add":
                    require_permission(actor, "submit_list")
                    offers = offer_client.search(form.get("item_code", ""), limit=1)
                    if not offers:
                        raise ValueError("\u05d4\u05de\u05d5\u05e6\u05e8 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0 \u05d1\u05e7\u05d8\u05dc\u05d5\u05d2 \u05d4\u05e2\u05d3\u05db\u05e0\u05d9.")
                    basket = basket_store.add(actor.id, offers[0], form.get("quantity", "1"))
                    html = _page("\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc", render_shufersal_basket(actor.id, basket))
                elif route.path == "/retailers/shufersal/basket/remove":
                    require_permission(actor, "submit_list")
                    basket = basket_store.remove(actor.id, form.get("item_code", ""))
                    html = _page("\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc", render_shufersal_basket(actor.id, basket))
                elif route.path == "/retailers/shufersal/basket/clear":
                    require_permission(actor, "submit_list")
                    basket = basket_store.clear(actor.id)
                    html = _page("\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc", render_shufersal_basket(actor.id, basket))
                elif route.path == "/admin/profile":
                    html = update_delivery_profile_from_form(actor, form, _store(profile_path))
                elif route.path == "/orders/quotes":
                    require_permission(actor, "submit_list")
                    items_raw = form.get("items", "")
                    items = parse_shopping_list(items_raw)
                    matches = tuple(
                        (item, offer_client.search(item, limit=5))
                        for item in items
                    )
                    html = _page(
                        "\u05d4\u05ea\u05d0\u05de\u05ea \u05de\u05d5\u05e6\u05e8\u05d9\u05dd",
                        render_shufersal_match_form(actor.id, items_raw, matches),
                    )
                elif route.path == "/orders/quotes/manual":
                    require_permission(actor, "submit_list")
                    html = _page(
                        "\u05d4\u05e6\u05e2\u05d5\u05ea \u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9\u05dd",
                        render_quote_form(actor.id, form.get("items", "")),
                    )
                elif route.path == "/orders/shufersal-match":
                    require_permission(actor, "resolve_product_exceptions")
                    items_raw = form.get("items", "")
                    items = parse_shopping_list(items_raw)
                    selected_offers: list[ShufersalProductOffer] = []
                    for index, item in enumerate(items):
                        item_code = form.get(f"selection_{index}", "").strip()
                        if not item_code:
                            raise ValueError(f"\u05d9\u05e9 \u05dc\u05d1\u05d7\u05d5\u05e8 \u05de\u05d5\u05e6\u05e8 \u05e2\u05d1\u05d5\u05e8 {item}.")
                        offers = offer_client.search(item_code, limit=1)
                        if not offers or offers[0].product.item_code != item_code:
                            raise ValueError("\u05d4\u05de\u05d5\u05e6\u05e8 \u05e9\u05e0\u05d1\u05d7\u05e8 \u05d0\u05d9\u05e0\u05d5 \u05e2\u05d5\u05d3 \u05d1\u05e7\u05d8\u05dc\u05d5\u05d2 \u05d4\u05e2\u05d3\u05db\u05e0\u05d9.")
                        selected_offers.append(offers[0])
                    basket_store.clear(actor.id)
                    basket = ShufersalBasket()
                    for offer in selected_offers:
                        basket = basket_store.add(actor.id, offer, "1")
                    html = _page(
                        "\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05d4\u05d6\u05de\u05e0\u05d4",
                        render_shufersal_basket_quote(actor.id, basket),
                    )
                elif route.path == "/orders/recommend":
                    require_permission(actor, "choose_fulfillment")
                    html = _page("\u05d4\u05de\u05dc\u05e6\u05d4 \u05dc\u05d4\u05d6\u05de\u05e0\u05d4", render_comparison(actor.id, compare_order_form(form)))
                elif route.path == "/orders/approve":
                    require_permission(actor, "approve_cart_preparation")
                    html = _page("\u05d4\u05db\u05e0\u05ea \u05d4\u05e1\u05dc \u05d0\u05d5\u05e9\u05e8\u05d4", render_approval(form))
                else:
                    self._send_html(render_error("\u05d4\u05e2\u05de\u05d5\u05d3 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0."), status=404)
                    return
            except PermissionError as exc:
                message = str(exc) if str(exc) == BUDGET_ACK_TEXT_HE else "\u05d0\u05d9\u05df \u05d4\u05e8\u05e9\u05d0\u05d4 \u05dc\u05d1\u05e6\u05e2 \u05e4\u05e2\u05d5\u05dc\u05d4 \u05d6\u05d5."
                self._send_html(render_error(message), status=403)
                return
            except ShufersalFeedError as exc:
                self._send_html(render_error(str(exc)), status=502)
                return
            except ValueError as exc:
                self._send_html(render_error(str(exc)), status=400)
                return
            self._send_html(html)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, html: str, status: int = 200) -> None:
            self._last_response_code = status
            encoded = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return GroceryAgentHandler


def render_home(actor: User, store: DeliveryProfileStore) -> str:
    profile_summary = _profile_summary(store)
    actions = [
        ("\u05d4\u05d2\u05e9\u05ea \u05e8\u05e9\u05d9\u05de\u05ea \u05e7\u05e0\u05d9\u05d5\u05ea", can(actor, "submit_list")),
        ("\u05d8\u05d9\u05e4\u05d5\u05dc \u05d1\u05d7\u05e8\u05d9\u05d2\u05d5\u05ea \u05de\u05d5\u05e6\u05e8\u05d9\u05dd", can(actor, "resolve_product_exceptions")),
        ("\u05d1\u05d7\u05d9\u05e8\u05ea \u05de\u05e9\u05dc\u05d5\u05d7 \u05d0\u05d5 \u05d0\u05d9\u05e1\u05d5\u05e3", can(actor, "choose_fulfillment")),
        ("\u05d0\u05d9\u05e9\u05d5\u05e8 \u05d7\u05e8\u05d9\u05d2\u05ea \u05ea\u05e7\u05e6\u05d9\u05d1", can(actor, "approve_budget_warning")),
        ("\u05d0\u05d9\u05e9\u05d5\u05e8 \u05d4\u05db\u05e0\u05ea \u05e1\u05dc", can(actor, "approve_cart_preparation")),
        ("\u05e2\u05e8\u05d9\u05db\u05ea \u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7", can(actor, "edit_delivery_profile")),
    ]
    action_items = "\n".join(
        f"<li><span>{escape(label)}</span><strong>{_permission_label(allowed)}</strong></li>"
        for label, allowed in actions
    )
    budget = BudgetPolicy()
    warning_text = BUDGET_ACK_TEXT_HE if budget.requires_acknowledgement(money("800.01")) else ""
    return _page(
        "\u05e1\u05d5\u05db\u05df \u05d4\u05e7\u05e0\u05d9\u05d5\u05ea",
        f"""
        <section class="toolbar">
          <a href="/?actor=shay">\u05e9\u05d9</a>
          <a href="/?actor=michal">\u05de\u05d9\u05db\u05dc</a>
          <a class="primary-link" href="/orders/new?actor={escape(actor.id)}">\u05d4\u05d6\u05de\u05e0\u05d4 \u05d7\u05d3\u05e9\u05d4</a>
          <a href="/retailers/shufersal?actor={escape(actor.id)}">\u05de\u05d7\u05d9\u05e8\u05d9 \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc</a>
          <a href="/admin/profile?actor=shay">\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7</a>
        </section>
        <section class="band">
          <h1>\u05e1\u05d5\u05db\u05df \u05d4\u05e7\u05e0\u05d9\u05d5\u05ea \u05d4\u05de\u05e9\u05e4\u05d7\u05ea\u05d9</h1>
          <p class="muted">\u05de\u05d7\u05d5\u05d1\u05e8/\u05ea \u05d1\u05ea\u05d5\u05e8 {escape(_actor_display_name(actor))}</p>
          <p class="profile">{profile_summary}</p>
        </section>
        <section class="grid">
          <div>
            <h2>\u05d4\u05e8\u05e9\u05d0\u05d5\u05ea \u05ea\u05d4\u05dc\u05d9\u05da</h2>
            <ul class="rules">{action_items}</ul>
          </div>
          <div>
            <h2>\u05de\u05d3\u05d9\u05e0\u05d9\u05d5\u05ea \u05ea\u05e7\u05e6\u05d9\u05d1</h2>
            <dl>
              <dt>\u05e1\u05e3</dt><dd>\u20aa800.00</dd>
              <dt>\u05d4\u05ea\u05e8\u05d0\u05d4 \u05d4\u05d7\u05dc \u05de\u05be</dt><dd>\u20aa800.01</dd>
              <dt>\u05e0\u05d5\u05e1\u05d7 \u05d0\u05d9\u05e9\u05d5\u05e8</dt><dd>{escape(warning_text)}</dd>
            </dl>
          </div>
          <div>
            <h2>\u05d4\u05e2\u05d3\u05e4\u05ea \u05d0\u05d9\u05e1\u05d5\u05e3</h2>
            <dl>
              <dt>\u05e9\u05d9\u05d8\u05d4</dt><dd>\u05de\u05e9\u05dc\u05d5\u05d7 \u05d0\u05d5 \u05d0\u05d9\u05e1\u05d5\u05e3</dd>
              <dt>\u05d0\u05d6\u05d5\u05e8</dt><dd>\u05e2\u05de\u05e7 \u05d7\u05e4\u05e8 \u05d1\u05dc\u05d1\u05d3</dd>
              <dt>\u05d7\u05dc\u05d5\u05df \u05de\u05d5\u05e2\u05d3\u05e3</dt><dd>16:30\u201318:30 \u05e9\u05e2\u05d5\u05df \u05d9\u05e9\u05e8\u05d0\u05dc</dd>
            </dl>
          </div>
        </section>
        """,
    )


def render_shufersal_search(
    actor_id: str,
    query: str = "",
    products: tuple[ShufersalProductOffer, ...] = (),
) -> str:
    if products:
        rows = "".join(_render_shufersal_offer_row(actor_id, offer) for offer in products)
        results = f"""
        <section class="table-band">
          <h2>\u05ea\u05d5\u05e6\u05d0\u05d5\u05ea ({len(products)})</h2>
          <div class="table-wrap"><table>
            <thead><tr><th>\u05de\u05d5\u05e6\u05e8</th><th>\u05d1\u05e8\u05e7\u05d5\u05d3</th><th>\u05de\u05d7\u05d9\u05e8 \u05e8\u05d2\u05d9\u05dc</th><th>\u05de\u05d7\u05d9\u05e8 \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9 \u05de\u05d5\u05e2\u05e8\u05da</th><th>\u05de\u05d1\u05e6\u05e2\u05d9\u05dd</th><th>\u05d9\u05d7\u05d9\u05d3\u05d4</th><th>\u05dc\u05e1\u05dc</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
        </section>
        """
    elif query:
        results = '<section class="band"><p>\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0\u05d5 \u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05ea\u05d5\u05d0\u05de\u05d9\u05dd.</p></section>'
    else:
        results = ""
    return f"""
    <section class="toolbar">
      <a href="/?actor={escape(actor_id)}">\u05d7\u05d6\u05e8\u05d4</a>
      <a href="/retailers/shufersal/basket?actor={escape(actor_id)}">\u05d4\u05e1\u05dc \u05e9\u05dc\u05d9</a>
      <a href="/retailers/shufersal/status?actor={escape(actor_id)}">\u05de\u05e6\u05d1 \u05d4\u05d7\u05d9\u05d1\u05d5\u05e8</a>
    </section>
    <section class="band">
      <p class="eyebrow">\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE</p>
      <h1>\u05d7\u05d9\u05e4\u05d5\u05e9 \u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d5\u05de\u05d1\u05e6\u05e2\u05d9\u05dd</h1>
      <p class="muted">\u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d5\u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05e0\u05e7\u05e8\u05d0\u05d9\u05dd \u05de\u05e7\u05d5\u05d1\u05e6\u05d9 \u05d4\u05e9\u05e7\u05d9\u05e4\u05d5\u05ea \u05d4\u05e8\u05e9\u05de\u05d9\u05d9\u05dd. \u05de\u05d1\u05e6\u05e2\u05d9 \u05de\u05d5\u05e2\u05d3\u05d5\u05df, \u05e7\u05d5\u05e4\u05d5\u05df \u05d0\u05d5 \u05db\u05de\u05d5\u05ea \u05de\u05d5\u05e6\u05d2\u05d9\u05dd \u05d0\u05da \u05d0\u05d9\u05e0\u05dd \u05de\u05d5\u05e4\u05d7\u05ea\u05d9\u05dd \u05d0\u05d5\u05d8\u05d5\u05de\u05d8\u05d9\u05ea. \u05d6\u05de\u05d9\u05e0\u05d5\u05ea, \u05d3\u05de\u05d9 \u05de\u05e9\u05dc\u05d5\u05d7 \u05d5\u05de\u05d7\u05d9\u05e8 \u05e1\u05d5\u05e4\u05d9 \u05de\u05d0\u05d5\u05e9\u05e8\u05d9\u05dd \u05d1\u05e7\u05d5\u05e4\u05d4.</p>
    </section>
    <form method="post" action="/retailers/shufersal" class="form">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <label>\u05e9\u05dd \u05de\u05d5\u05e6\u05e8 \u05d0\u05d5 \u05d1\u05e8\u05e7\u05d5\u05d3
        <input name="query" value="{escape(query)}" required autocomplete="off">
      </label>
      <button type="submit">\u05d7\u05d9\u05e4\u05d5\u05e9</button>
    </form>
    {results}
    """


def _render_shufersal_offer_row(actor_id: str, offer: ShufersalProductOffer) -> str:
    product = offer.product
    estimated = f"\u20aa{offer.effective_price_ils}"
    if offer.effective_price_ils == product.price_ils:
        estimated = "\u2014"
    return (
        f"<tr><td>{escape(product.name)}</td><td>{escape(product.item_code)}</td>"
        f"<td>\u20aa{product.price_ils}</td><td>{estimated}</td>"
        f"<td>{_promotion_summary(offer)}</td>"
        f"<td>{escape(product.unit_quantity or product.unit_of_measure)}"
        f"{' (\u05d1\u05de\u05e9\u05e7\u05dc)' if product.weighted else ''}</td>"
        f'<td><form method="post" action="/retailers/shufersal/basket/add" class="inline-form">'
        f'<input type="hidden" name="actor" value="{escape(actor_id)}">'
        f'<input type="hidden" name="item_code" value="{escape(product.item_code)}">'
        f'<input type="number" name="quantity" value="1" min="0.01" max="100" step="0.01" aria-label="\u05db\u05de\u05d5\u05ea">'
        f'<button type="submit">\u05d4\u05d5\u05e1\u05e4\u05d4</button></form></td></tr>'
    )


def _promotion_summary(offer: ShufersalProductOffer) -> str:
    if not offer.promotions:
        return "\u05d0\u05d9\u05df \u05de\u05d1\u05e6\u05e2 \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9"
    labels: list[str] = []
    for promotion in offer.promotions[:2]:
        restrictions: list[str] = []
        item = next(
            (item for item in promotion.items if item.item_code == offer.product.item_code),
            None,
        )
        if promotion.club_only:
            restrictions.append("\u05de\u05d5\u05e2\u05d3\u05d5\u05df")
        if promotion.coupon_required:
            restrictions.append("\u05e7\u05d5\u05e4\u05d5\u05df")
        if item is not None and item.minimum_quantity > 1:
            restrictions.append(f"\u05de\u05d9\u05e0\u05d9\u05de\u05d5\u05dd {item.minimum_quantity:g}")
        suffix = f" ({', '.join(restrictions)})" if restrictions else ""
        labels.append(escape(promotion.description or "\u05de\u05d1\u05e6\u05e2") + escape(suffix))
    return "<br>".join(labels)


def render_shufersal_match_form(
    actor_id: str,
    items_raw: str,
    matches: tuple[tuple[str, tuple[ShufersalProductOffer, ...]], ...],
) -> str:
    sections: list[str] = []
    all_resolved = True
    for index, (requested_item, offers) in enumerate(matches):
        if offers:
            options = "".join(
                _render_match_option(index, offer)
                for offer in offers
            )
        else:
            all_resolved = False
            options = '<p class="warning">\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0\u05d4 \u05d4\u05ea\u05d0\u05de\u05d4 \u05d1\u05e7\u05d8\u05dc\u05d5\u05d2 \u05d4\u05e6\u05d9\u05d1\u05d5\u05e8\u05d9.</p>'
        sections.append(
            f'<fieldset class="match-group"><legend>{escape(requested_item)}</legend>'
            f'<div class="match-options">{options}</div></fieldset>'
        )

    disabled = "" if all_resolved and matches else "disabled"
    return f"""
    <section class="toolbar">
      <a href="/orders/new?actor={escape(actor_id)}">\u05d7\u05d6\u05e8\u05d4 \u05dc\u05e8\u05e9\u05d9\u05de\u05d4</a>
      <a href="/retailers/shufersal/status?actor={escape(actor_id)}">\u05de\u05e6\u05d1 \u05d4\u05d7\u05d9\u05d1\u05d5\u05e8</a>
    </section>
    <section class="band">
      <p class="eyebrow">\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE</p>
      <h1>\u05d1\u05d7\u05d9\u05e8\u05ea \u05d4\u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05d4\u05de\u05d3\u05d5\u05d9\u05e7\u05d9\u05dd</h1>
      <p class="muted">\u05d4\u05de\u05d7\u05d9\u05e8\u05d9\u05dd \u05d5\u05d4\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05e0\u05e7\u05e8\u05d0\u05d5 \u05db\u05e2\u05ea \u05de\u05d4\u05e7\u05d8\u05dc\u05d5\u05d2 \u05d4\u05e6\u05d9\u05d1\u05d5\u05e8\u05d9. \u05d9\u05e9 \u05dc\u05d1\u05d7\u05d5\u05e8 \u05d0\u05e4\u05e9\u05e8\u05d5\u05ea \u05d0\u05d7\u05ea \u05dc\u05db\u05dc \u05e9\u05d5\u05e8\u05d4; \u05d4\u05de\u05e2\u05e8\u05db\u05ea \u05dc\u05d0 \u05ea\u05e0\u05d7\u05e9 \u05d0\u05d9\u05d6\u05d4 \u05de\u05d5\u05e6\u05e8 \u05e8\u05e6\u05d9\u05ea.</p>
    </section>
    <form method="post" action="/orders/shufersal-match" class="quote-form">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <textarea name="items" hidden>{escape(items_raw)}</textarea>
      {''.join(sections)}
      <div class="form-actions"><button type="submit" {disabled}>\u05d4\u05de\u05e9\u05da \u05e2\u05dd \u05d4\u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05e9\u05e0\u05d1\u05d7\u05e8\u05d5</button></div>
    </form>
    <form method="post" action="/orders/quotes/manual" class="form manual-fallback">
      <input type="hidden" name="actor" value="{escape(actor_id)}">
      <textarea name="items" hidden>{escape(items_raw)}</textarea>
      <button type="submit" class="secondary">\u05de\u05e2\u05d1\u05e8 \u05dc\u05d4\u05e9\u05d5\u05d5\u05d0\u05d4 \u05d9\u05d3\u05e0\u05d9\u05ea</button>
    </form>
    """


def _render_match_option(index: int, offer: ShufersalProductOffer) -> str:
    product = offer.product
    price = f"\u20aa{product.price_ils}"
    if offer.effective_price_ils < product.price_ils:
        price += f" | \u05de\u05d7\u05d9\u05e8 \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9 \u05de\u05d5\u05e2\u05e8\u05da \u20aa{offer.effective_price_ils}"
    unit = escape(product.unit_quantity or product.unit_of_measure)
    return f"""
    <label class="match-option">
      <input type="radio" name="selection_{index}" value="{escape(product.item_code)}" required>
      <span><strong>{escape(product.name)}</strong><br>
      <small>{price} | {unit} | {_promotion_summary(offer)}</small></span>
    </label>
    """


def render_shufersal_basket_quote(actor_id: str, basket: ShufersalBasket) -> str:
    if not basket.lines:
        raise ValueError("\u05d9\u05e9 \u05dc\u05d1\u05d7\u05d5\u05e8 \u05dc\u05e4\u05d7\u05d5\u05ea \u05de\u05d5\u05e6\u05e8 \u05d0\u05d7\u05d3.")
    prefill = RetailerQuotePrefill(
        retailer="\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE",
        subtotal=basket.regular_total_ils,
        promotions=basket.public_savings_ils,
        weighted=basket.has_weighted_items,
    )
    return render_quote_form(
        actor_id,
        basket.shopping_list_text,
        prefill=prefill,
    )

def render_shufersal_status(actor_id: str, status: ShufersalConnectionStatus) -> str:
    updated = escape(status.latest_price_update or "\u05dc\u05d0 \u05e0\u05de\u05e1\u05e8")
    return f"""
    <section class="toolbar">
      <a href="/retailers/shufersal?actor={escape(actor_id)}">\u05d7\u05d6\u05e8\u05d4 \u05dc\u05d7\u05d9\u05e4\u05d5\u05e9</a>
    </section>
    <section class="band success">
      <p class="eyebrow">\u05e9\u05d5\u05e4\u05e8\u05e1\u05dc ONLINE, \u05e1\u05e0\u05d9\u05e3 413</p>
      <h1>\u05d4\u05d7\u05d9\u05d1\u05d5\u05e8 \u05dc\u05e0\u05ea\u05d5\u05e0\u05d9\u05dd \u05d4\u05e6\u05d9\u05d1\u05d5\u05e8\u05d9\u05d9\u05dd \u05e4\u05e2\u05d9\u05dc</h1>
      <dl>
        <dt>\u05de\u05d5\u05e6\u05e8\u05d9\u05dd \u05e9\u05e0\u05d8\u05e2\u05e0\u05d5</dt><dd>{status.product_count}</dd>
        <dt>\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9\u05d9\u05dd</dt><dd>{status.promotion_count}</dd>
        <dt>\u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d7\u05d9\u05e8 \u05d0\u05d7\u05e8\u05d5\u05df \u05d1\u05e7\u05d5\u05d1\u05e5</dt><dd>{updated}</dd>
      </dl>
    </section>
    <section class="band">
      <h2>\u05de\u05d4 \u05e2\u05d3\u05d9\u05d9\u05df \u05d3\u05d5\u05e8\u05e9 \u05d0\u05d9\u05e9\u05d5\u05e8 \u05d1\u05e7\u05d5\u05e4\u05d4</h2>
      <p class="muted">\u05d6\u05de\u05d9\u05e0\u05d5\u05ea \u05dc\u05e4\u05d9 \u05db\u05ea\u05d5\u05d1\u05ea, \u05d3\u05de\u05d9 \u05de\u05e9\u05dc\u05d5\u05d7 \u05d5\u05e9\u05d9\u05e8\u05d5\u05ea, \u05d0\u05e4\u05e9\u05e8\u05d5\u05d9\u05d5\u05ea \u05d0\u05d9\u05e1\u05d5\u05e3, \u05d7\u05dc\u05d5\u05e0\u05d5\u05ea \u05d6\u05de\u05df, \u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05d0\u05d9\u05e9\u05d9\u05d9\u05dd \u05d5\u05de\u05d7\u05d9\u05e8 \u05d4\u05e7\u05d5\u05e4\u05d4. \u05dc\u05d0 \u05de\u05d5\u05e2\u05d1\u05e8\u05d9\u05dd \u05e4\u05e8\u05d8\u05d9 \u05d4\u05ea\u05d7\u05d1\u05e8\u05d5\u05ea, \u05db\u05ea\u05d5\u05d1\u05ea \u05d0\u05d5 \u05ea\u05e9\u05dc\u05d5\u05dd.</p>
    </section>
    """

def render_shufersal_basket(actor_id: str, basket: ShufersalBasket) -> str:
    toolbar = f"""
    <section class="toolbar">
      <a href="/retailers/shufersal?actor={escape(actor_id)}">\u05d4\u05de\u05e9\u05da \u05d7\u05d9\u05e4\u05d5\u05e9</a>
      <a href="/retailers/shufersal/basket/compare?actor={escape(actor_id)}">\u05de\u05e2\u05d1\u05e8 \u05dc\u05d4\u05e9\u05d5\u05d5\u05d0\u05ea \u05d4\u05d6\u05de\u05e0\u05d4</a>
    </section>
    """
    if not basket.lines:
        return toolbar + '<section class="band"><h1>\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc</h1><p>\u05d4\u05e1\u05dc \u05e2\u05d3\u05d9\u05d9\u05df \u05e8\u05d9\u05e7.</p></section>'

    rows = "".join(
        f"<tr><td>{escape(line.offer.product.name)}</td><td>{line.quantity:g}</td>"
        f"<td>\u20aa{line.offer.product.price_ils}</td><td>\u20aa{line.estimated_total_ils}</td>"
        f'<td><form method="post" action="/retailers/shufersal/basket/remove" class="inline-form">'
        f'<input type="hidden" name="actor" value="{escape(actor_id)}">'
        f'<input type="hidden" name="item_code" value="{escape(line.offer.product.item_code)}">'
        f'<button type="submit">\u05d4\u05e1\u05e8\u05d4</button></form></td></tr>'
        for line in basket.lines
    )
    weight_notice = (
        '<p class="warning">\u05d4\u05e1\u05db\u05d5\u05dd \u05db\u05d5\u05dc\u05dc \u05d4\u05e2\u05e8\u05db\u05ea \u05de\u05e9\u05e7\u05dc; \u05d4\u05d7\u05d9\u05d5\u05d1 \u05d4\u05e1\u05d5\u05e4\u05d9 \u05e2\u05e9\u05d5\u05d9 \u05dc\u05d4\u05e9\u05ea\u05e0\u05d5\u05ea \u05dc\u05e4\u05d9 \u05d4\u05de\u05e9\u05e7\u05dc \u05d1\u05e4\u05d5\u05e2\u05dc.</p>'
        if basket.has_weighted_items
        else ""
    )
    return toolbar + f"""
    <section class="band">
      <h1>\u05e1\u05dc \u05e9\u05d5\u05e4\u05e8\u05e1\u05dc \u05de\u05e7\u05d5\u05de\u05d9</h1>
      <p class="muted">\u05d4\u05e1\u05dc \u05e0\u05e9\u05de\u05e8 \u05e8\u05e7 \u05d1\u05d6\u05de\u05df \u05e9\u05d4\u05e4\u05d5\u05e8\u05d8\u05dc \u05e4\u05d5\u05e2\u05dc. \u05d4\u05d5\u05d0 \u05d0\u05d9\u05e0\u05d5 \u05e1\u05dc \u05d1\u05d0\u05ea\u05e8 \u05d4\u05e7\u05de\u05e2\u05d5\u05e0\u05d0\u05d9.</p>
      {weight_notice}
    </section>
    <section class="table-band"><div class="table-wrap"><table>
      <thead><tr><th>\u05de\u05d5\u05e6\u05e8</th><th>\u05db\u05de\u05d5\u05ea</th><th>\u05de\u05d7\u05d9\u05e8 \u05e8\u05d2\u05d9\u05dc</th><th>\u05e1\u05db\u05d5\u05dd \u05de\u05d5\u05e2\u05e8\u05da</th><th></th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div></section>
    <section class="band">
      <dl><dt>\u05e1\u05db\u05d5\u05dd \u05e8\u05d2\u05d9\u05dc</dt><dd>\u20aa{basket.regular_total_ils}</dd>
      <dt>\u05d7\u05d9\u05e1\u05db\u05d5\u05df \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9 \u05e9\u05d7\u05d5\u05e9\u05d1</dt><dd>\u20aa{basket.public_savings_ils}</dd>
      <dt>\u05e1\u05db\u05d5\u05dd \u05de\u05d5\u05e2\u05e8\u05da</dt><dd><strong>\u20aa{basket.estimated_total_ils}</strong></dd></dl>
      <p class="muted">\u05d3\u05de\u05d9 \u05de\u05e9\u05dc\u05d5\u05d7, \u05d3\u05de\u05d9 \u05e9\u05d9\u05e8\u05d5\u05ea, \u05d6\u05de\u05d9\u05e0\u05d5\u05ea \u05d5\u05de\u05d1\u05e6\u05e2\u05d9\u05dd \u05d0\u05d9\u05e9\u05d9\u05d9\u05dd \u05e0\u05d1\u05d3\u05e7\u05d9\u05dd \u05e8\u05e7 \u05d1\u05e7\u05d5\u05e4\u05d4.</p>
      <form method="post" action="/retailers/shufersal/basket/clear">
        <input type="hidden" name="actor" value="{escape(actor_id)}">
        <button type="submit" class="secondary">\u05e0\u05d9\u05e7\u05d5\u05d9 \u05d4\u05e1\u05dc</button>
      </form>
    </section>
    """


def _actor_display_name(actor: User) -> str:
    return "\u05e9\u05d9" if actor.id == "shay" else "\u05de\u05d9\u05db\u05dc"


def _permission_label(allowed: bool) -> str:
    return "\u05de\u05d5\u05e8\u05e9\u05d4" if allowed else "\u05dc\u05d1\u05e2\u05dc\u05d9\u05dd \u05d1\u05dc\u05d1\u05d3"


def render_profile_form(actor: User) -> str:
    disabled = "" if can(actor, "edit_delivery_profile") else "disabled"
    notice = ("\u05e8\u05e7 \u05e9\u05d9 \u05e8\u05e9\u05d0\u05d9 \u05dc\u05e2\u05e8\u05d5\u05da \u05d0\u05ea \u05d4\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05d4\u05de\u05d5\u05e6\u05e4\u05df." if disabled else "\u05d9\u05e9 \u05dc\u05d4\u05d6\u05d9\u05df \u05d0\u05ea \u05d4\u05db\u05ea\u05d5\u05d1\u05ea \u05d4\u05de\u05dc\u05d0\u05d4 \u05e8\u05e7 \u05d1\u05d3\u05e4\u05d3\u05e4\u05df \u05de\u05e7\u05d5\u05de\u05d9 \u05d6\u05d4.")
    return _page(
        "\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7",
        f"""
        <section class="toolbar">
          <a href="/?actor={escape(actor.id)}">\u05d7\u05d6\u05e8\u05d4</a>
        </section>
        <section class="band">
          <h1>\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7</h1>
          <p class="profile">{MASKED_DELIVERY_ADDRESS}</p>
          <p class="muted">{escape(notice)}</p>
        </section>
        <form method="post" action="/admin/profile" class="form">
          <input type="hidden" name="actor" value="{escape(actor.id)}">
          <label>\u05d9\u05d9\u05e9\u05d5\u05d1 <input name="city" value="\u05e4\u05e8\u05d3\u05e1\u05d9\u05d4" required {disabled}></label>
          <label>\u05db\u05ea\u05d5\u05d1\u05ea \u05de\u05dc\u05d0\u05d4 <input name="address_line" autocomplete="street-address" required {disabled}></label>
          <label>\u05d4\u05e2\u05e8\u05d4 \u05dc\u05de\u05e7\u05d1\u05dc/\u05ea <input name="recipient_note" {disabled}></label>
          <button type="submit" {disabled}>\u05e9\u05de\u05d9\u05e8\u05ea \u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05d5\u05e6\u05e4\u05df</button>
        </form>
        """,
    )


def update_delivery_profile_from_form(actor: User, form: dict[str, str], store: DeliveryProfileStore) -> str:
    profile = DeliveryProfileAdminForm(store).submit(
        actor,
        DeliveryAddress(
            city=form.get("city", ""),
            address_line=form.get("address_line", ""),
            recipient_note=form.get("recipient_note", ""),
        ),
        profile_id=form.get("profile_id") or None,
    )
    response = profile_api_response(profile)
    return _page(
        "\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05d4\u05de\u05e9\u05dc\u05d5\u05d7 \u05e0\u05e9\u05de\u05e8",
        f"""
        <section class="band">
          <h1>\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05d4\u05de\u05e9\u05dc\u05d5\u05d7 \u05e0\u05e9\u05de\u05e8</h1>
          <p class="profile">{escape(response["masked_address"])}</p>
          <p class="muted">\u05de\u05d6\u05d4\u05d4 \u05e4\u05e8\u05d5\u05e4\u05d9\u05dc: {escape(response["delivery_profile_id"])}</p>
          <a href="/">\u05d7\u05d6\u05e8\u05d4 \u05dc\u05e4\u05d5\u05e8\u05d8\u05dc</a>
        </section>
        """,
    )


def render_error(message: str) -> str:
    return _page("\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d4\u05e9\u05dc\u05d9\u05dd \u05d0\u05ea \u05d4\u05e4\u05e2\u05d5\u05dc\u05d4", f"<section class=\"band\"><h1>\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05d4\u05e9\u05dc\u05d9\u05dd \u05d0\u05ea \u05d4\u05e4\u05e2\u05d5\u05dc\u05d4</h1><p>{escape(message)}</p></section>")


def _profile_summary(store: DeliveryProfileStore) -> str:
    try:
        return escape(profile_api_response(store.load())["masked_address"])
    except (FileNotFoundError, CryptoError):
        return "\u05d8\u05e8\u05dd \u05e0\u05e9\u05de\u05e8 \u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05de\u05e9\u05dc\u05d5\u05d7."


def _store(path: Path) -> DeliveryProfileStore:
    return DeliveryProfileStore(path, EnvMasterKeyCryptoProvider.from_env())


def _actor(actor_id: str) -> User:
    if actor_id == "shay":
        return User(id="shay", display_name="\u05e9\u05d9", role=Role.OWNER)
    return User(id="michal", display_name="\u05de\u05d9\u05db\u05dc", role=Role.HOUSEHOLD_MEMBER)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #202124;
      --muted: #5f6368;
      --line: #d8dde3;
      --surface: #f7f9fb;
      --accent: #0f766e;
      --warn: #9a3412;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: white;
      direction: rtl;
      text-align: right;
    }}
    .toolbar {{
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 12px 20px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }}
    a, button {{
      min-height: 36px;
      border: 1px solid var(--accent);
      color: var(--accent);
      background: white;
      padding: 8px 12px;
      text-decoration: none;
      font-weight: 700;
      border-radius: 6px;
    }}
    .primary-link {{
      background: var(--accent);
      color: white;
    }}
    button {{
      background: var(--accent);
      color: white;
      cursor: pointer;
    }}
    button:disabled, input:disabled {{
      opacity: .55;
      cursor: not-allowed;
    }}
    .band {{
      padding: 28px 20px;
      border-bottom: 1px solid var(--line);
    }}
    h1, h2 {{ margin: 0 0 12px; letter-spacing: 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 18px; }}
    .muted {{ color: var(--muted); }}
    .profile {{
      display: inline-block;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      font-weight: 700;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
      padding: 20px;
    }}
    .rules {{
      list-style: none;
      padding: 0;
      margin: 0;
      border-top: 1px solid var(--line);
    }}
    .rules li, dl {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; font-weight: 700; }}
    .form {{
      display: grid;
      gap: 14px;
      max-width: 680px;
      padding: 20px;
    }}
    label {{ display: grid; gap: 6px; font-weight: 700; }}
    input, textarea, select {{
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
    }}
    textarea {{ resize: vertical; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 13px; font-weight: 700; text-transform: uppercase; }}
    .compact-list {{ margin: 12px 0 0; padding-inline-start: 20px; }}
    .quote-form {{ display: grid; gap: 18px; padding: 20px; }}
    fieldset {{ margin: 0; padding: 18px; border: 1px solid var(--line); border-radius: 6px; }}
    legend {{ padding: 0 6px; font-size: 18px; font-weight: 700; }}
    .fields {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .checks {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; }}
    .checks label, .ack {{ display: flex; grid-template-columns: none; align-items: center; gap: 8px; }}
    .checks input, .ack input {{ min-height: auto; width: 18px; height: 18px; }}
    .form-actions {{ display: flex; justify-content: flex-end; }}
    .inline-form {{ display: flex; align-items: center; gap: 6px; }}
    .inline-form input[type="number"] {{ width: 76px; min-height: 36px; }}
    .inline-form button {{ white-space: nowrap; }}
    .secondary {{ background: white; color: var(--accent); }}
    .match-options {{ display: grid; gap: 8px; }}
    .match-option {{
      display: flex;
      grid-template-columns: none;
      align-items: flex-start;
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font-weight: 400;
      cursor: pointer;
    }}
    .match-option:has(input:checked) {{ border-color: var(--accent); background: #eef8f3; }}
    .match-option input {{ width: 18px; height: 18px; min-height: auto; margin-top: 2px; }}
    .match-option small {{ color: var(--muted); white-space: normal; }}
    .manual-fallback {{ padding-top: 0; }}
    .connection-note {{
      padding: 12px;
      border-right: 4px solid var(--accent);
      background: #eef8f3;
    }}
    .table-band {{ padding: 20px; border-bottom: 1px solid var(--line); }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 10px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
    th {{ color: var(--muted); font-size: 13px; }}
    .total {{ font-size: 18px; }}
    .warning {{ color: var(--warn); }}
    .ok {{ color: var(--accent); font-weight: 700; }}
    .success {{ border-right: 5px solid var(--accent); }}
    @media (max-width: 640px) {{
      .toolbar {{ flex-wrap: wrap; }}
      .band, .grid, .quote-form, .form, .table-band {{ padding: 16px; }}
      .fields {{ grid-template-columns: 1fr; }}
      .form-actions button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


