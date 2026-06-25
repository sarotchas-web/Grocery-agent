from __future__ import annotations

import argparse
from pathlib import Path

from grocery_agent.crypto import EnvMasterKeyCryptoProvider
from grocery_agent.delivery_profile import (
    DeliveryAddress,
    DeliveryProfileAdminForm,
    DeliveryProfileStore,
    profile_api_response,
)
from grocery_agent.models import Role, User


DEFAULT_PROFILE_PATH = Path(".local") / "delivery-profile.enc"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grocery-agent")
    parser.add_argument("--profile-path", default=str(DEFAULT_PROFILE_PATH))
    subcommands = parser.add_subparsers(dest="command", required=True)

    update = subcommands.add_parser("delivery-profile-update")
    update.add_argument("--actor", required=True, choices=["shay", "michal"])
    update.add_argument("--city", required=True)
    update.add_argument("--address-line", required=True)
    update.add_argument("--recipient-note", default="")
    update.add_argument("--profile-id")

    show = subcommands.add_parser("delivery-profile-show")
    show.add_argument("--actor", required=True, choices=["shay", "michal"])

    args = parser.parse_args(argv)
    store = DeliveryProfileStore(Path(args.profile_path), EnvMasterKeyCryptoProvider.from_env())
    actor = _actor(args.actor)

    if args.command == "delivery-profile-update":
        form = DeliveryProfileAdminForm(store)
        profile = form.submit(
            actor,
            DeliveryAddress(
                city=args.city,
                address_line=args.address_line,
                recipient_note=args.recipient_note,
            ),
            profile_id=args.profile_id,
        )
        print(profile.masked_display())
        print(f"delivery_profile_id={profile.id}")
        return 0

    if args.command == "delivery-profile-show":
        profile = store.load()
        response = profile_api_response(profile)
        print(response["masked_address"])
        print(f"delivery_profile_id={response['delivery_profile_id']}")
        return 0

    parser.error("Unknown command")
    return 2


def _actor(actor_id: str) -> User:
    if actor_id == "shay":
        return User(id="shay", display_name="Shay", role=Role.OWNER)
    return User(id="michal", display_name="Michal", role=Role.HOUSEHOLD_MEMBER)


if __name__ == "__main__":
    raise SystemExit(main())
