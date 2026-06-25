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
from grocery_agent.permissions import can


DEFAULT_PROFILE_PATH = Path(".local") / "delivery-profile.enc"


def run(host: str = "127.0.0.1", port: int = 8765, profile_path: Path = DEFAULT_PROFILE_PATH) -> None:
    handler = build_handler(profile_path)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Grocery Agent portal: http://{host}:{port}")
    server.serve_forever()


def build_handler(profile_path: Path) -> type[BaseHTTPRequestHandler]:
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
            self.send_error(404)

        def do_POST(self) -> None:
            route = urlparse(self.path)
            if route.path != "/admin/profile":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            form = {key: values[0] for key, values in parse_qs(body).items()}
            actor = _actor(form.get("actor", "michal"))
            try:
                html = update_delivery_profile_from_form(actor, form, _store(profile_path))
            except PermissionError:
                self._send_html(render_error("Only Shay can edit the delivery profile."), status=403)
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
        ("Submit list", can(actor, "submit_list")),
        ("Resolve exceptions", can(actor, "resolve_product_exceptions")),
        ("Choose delivery or pickup", can(actor, "choose_fulfillment")),
        ("Approve budget warning", can(actor, "approve_budget_warning")),
        ("Approve cart preparation", can(actor, "approve_cart_preparation")),
        ("Edit delivery profile", can(actor, "edit_delivery_profile")),
    ]
    action_items = "\n".join(
        f"<li><span>{escape(label)}</span><strong>{'Allowed' if allowed else 'Owner only'}</strong></li>"
        for label, allowed in actions
    )
    budget = BudgetPolicy()
    warning_text = BUDGET_ACK_TEXT_HE if budget.requires_acknowledgement(money("800.01")) else ""
    return _page(
        "Grocery Agent",
        f"""
        <section class="toolbar">
          <a href="/?actor=shay">Shay</a>
          <a href="/?actor=michal">Michal</a>
          <a href="/admin/profile?actor=shay">Delivery profile</a>
        </section>
        <section class="band">
          <h1>Household Grocery Agent</h1>
          <p class="muted">Signed in as {escape(actor.display_name)}</p>
          <p class="profile">{profile_summary}</p>
        </section>
        <section class="grid">
          <div>
            <h2>Workflow Permissions</h2>
            <ul class="rules">{action_items}</ul>
          </div>
          <div>
            <h2>Budget Policy</h2>
            <dl>
              <dt>Threshold</dt><dd>ג‚×800.00</dd>
              <dt>Warning starts</dt><dd>ג‚×800.01</dd>
              <dt>Acknowledgement</dt><dd>{escape(warning_text)}</dd>
            </dl>
          </div>
          <div>
            <h2>Pickup Preference</h2>
            <dl>
              <dt>Mode</dt><dd>DELIVERY or PICKUP</dd>
              <dt>Area</dt><dd>Emek Hefer only</dd>
              <dt>Preferred window</dt><dd>16:30-18:30 Asia/Jerusalem</dd>
            </dl>
          </div>
        </section>
        """,
    )


def render_profile_form(actor: User) -> str:
    disabled = "" if can(actor, "edit_delivery_profile") else "disabled"
    notice = "Only Shay can edit this local encrypted profile." if disabled else "Enter the real address only in this local browser."
    return _page(
        "Delivery Profile",
        f"""
        <section class="toolbar">
          <a href="/?actor={escape(actor.id)}">Back</a>
        </section>
        <section class="band">
          <h1>Delivery Profile</h1>
          <p class="profile">{MASKED_DELIVERY_ADDRESS}</p>
          <p class="muted">{escape(notice)}</p>
        </section>
        <form method="post" action="/admin/profile" class="form">
          <input type="hidden" name="actor" value="{escape(actor.id)}">
          <label>City <input name="city" value="Pardesiya" required {disabled}></label>
          <label>Address line <input name="address_line" autocomplete="street-address" required {disabled}></label>
          <label>Recipient note <input name="recipient_note" {disabled}></label>
          <button type="submit" {disabled}>Save encrypted profile</button>
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
        "Delivery Profile Saved",
        f"""
        <section class="band">
          <h1>Delivery Profile Saved</h1>
          <p class="profile">{escape(response["masked_address"])}</p>
          <p class="muted">delivery_profile_id={escape(response["delivery_profile_id"])}</p>
          <a href="/">Return to portal</a>
        </section>
        """,
    )


def render_error(message: str) -> str:
    return _page("Not Allowed", f"<section class=\"band\"><h1>Not Allowed</h1><p>{escape(message)}</p></section>")


def _profile_summary(store: DeliveryProfileStore) -> str:
    try:
        return escape(profile_api_response(store.load())["masked_address"])
    except (FileNotFoundError, CryptoError):
        return "No delivery profile saved yet."


def _store(path: Path) -> DeliveryProfileStore:
    return DeliveryProfileStore(path, EnvMasterKeyCryptoProvider.from_env())


def _actor(actor_id: str) -> User:
    if actor_id == "shay":
        return User(id="shay", display_name="Shay", role=Role.OWNER)
    return User(id="michal", display_name="Michal", role=Role.HOUSEHOLD_MEMBER)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
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
    input {{
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


