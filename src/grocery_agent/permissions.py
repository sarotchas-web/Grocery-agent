from grocery_agent.models import Role, User


OWNER_ACTIONS = {
    "manage_allowlist",
    "edit_delivery_profile",
    "change_budget_threshold",
    "change_pickup_preferences",
}

HOUSEHOLD_ACTIONS = {
    "submit_list",
    "resolve_product_exceptions",
    "choose_fulfillment",
    "approve_budget_warning",
    "approve_cart_preparation",
    "use_delivery_profile",
}


def can(user: User, action: str) -> bool:
    if user.role == Role.OWNER:
        return action in OWNER_ACTIONS or action in HOUSEHOLD_ACTIONS
    return action in HOUSEHOLD_ACTIONS


def require_permission(user: User, action: str) -> None:
    if not can(user, action):
        raise PermissionError(f"{user.display_name} may not perform {action}")
