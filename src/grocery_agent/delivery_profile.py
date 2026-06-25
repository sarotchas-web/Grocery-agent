from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from grocery_agent.crypto import CryptoProvider
from grocery_agent.models import User
from grocery_agent.permissions import require_permission


MASKED_DELIVERY_ADDRESS = "\u05db\u05ea\u05d5\u05d1\u05ea \u05de\u05e9\u05dc\u05d5\u05d7: \u05e4\u05e8\u05d3\u05e1\u05d9\u05d4, \u05db\u05ea\u05d5\u05d1\u05ea \u05de\u05d0\u05d5\u05de\u05ea\u05ea"


@dataclass(frozen=True)
class DeliveryAddress:
    city: str
    address_line: str
    recipient_note: str = ""


@dataclass(frozen=True)
class DeliveryProfile:
    id: str
    address: DeliveryAddress

    def masked_display(self) -> str:
        return MASKED_DELIVERY_ADDRESS


class DeliveryProfileStore:
    def __init__(self, path: Path, crypto: CryptoProvider):
        self.path = path
        self.crypto = crypto

    def save(self, profile: DeliveryProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": profile.id,
            "address": {
                "city": profile.address.city,
                "address_line": profile.address.address_line,
                "recipient_note": profile.address.recipient_note,
            },
        }
        self.path.write_text(self.crypto.encrypt_json(payload), encoding="utf-8")

    def load(self) -> DeliveryProfile:
        payload = self.crypto.decrypt_json(self.path.read_text(encoding="utf-8"))
        address = payload["address"]
        return DeliveryProfile(
            id=payload["id"],
            address=DeliveryAddress(
                city=address["city"],
                address_line=address["address_line"],
                recipient_note=address.get("recipient_note", ""),
            ),
        )


class DeliveryProfileAdminForm:
    """Owner-only local form boundary for manual delivery address entry."""

    def __init__(self, store: DeliveryProfileStore):
        self.store = store

    def submit(self, user: User, address: DeliveryAddress, profile_id: str | None = None) -> DeliveryProfile:
        require_permission(user, "edit_delivery_profile")
        profile = DeliveryProfile(id=profile_id or f"dp_{uuid4().hex}", address=address)
        self.store.save(profile)
        return profile


def audit_delivery_profile_used(profile: DeliveryProfile) -> dict:
    return {"event": "delivery_profile_used", "delivery_profile_id": profile.id}


def profile_api_response(profile: DeliveryProfile) -> dict:
    return {"delivery_profile_id": profile.id, "masked_address": profile.masked_display()}


def profile_email_fragment(profile: DeliveryProfile) -> str:
    return profile.masked_display()


def assert_no_delivery_address_leak(profile: DeliveryProfile, *surfaces: str) -> None:
    serialized = json.dumps(surfaces, ensure_ascii=False)
    if profile.address.address_line and profile.address.address_line in serialized:
        raise AssertionError("Decrypted delivery address leaked")

