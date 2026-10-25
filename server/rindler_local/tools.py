"""Tool definitions generated from a mapping.

One tool per mapping action, plus ``start_session`` and ``close_session``. Nothing else:
a tool exists only if the mapping defines the action, so the model never sees a tool
the site cannot run. Tools come back MCP-style (``inputSchema``); ``to_anthropic`` turns
them into the Messages API shape (``input_schema``).
"""

from __future__ import annotations

from typing import Any

from .mapping import Mapping

START_SESSION = {
    "name": "start_session",
    "description": (
        "Open a new browser session on the site and return the first screen with the "
        "actions available there. Call this first."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Site URL to open, e.g. https://vhlistings.com"}},
        "required": ["url"],
    },
}

CLOSE_SESSION = {
    "name": "close_session",
    "description": "Close the browser session. Only needed when you are completely finished with the site.",
    "inputSchema": {"type": "object", "properties": {}},
}

# Used when a mapping action has no "description" of its own.
DEFAULT_DESCRIPTIONS = {
    "search_products": "Search the site for products. Returns the matching products (name, price) in data.products.",
    "view_product": "Open a product's detail page. Pass the product name, or a distinctive part of it, as listed in data.products.",
    "add_to_cart": "Add one unit of a product to the cart.",
    "view_cart": "Open the cart. Returns the cart contents in data.cart_items.",
    "remove_from_cart": "Remove an item from the cart. Pass its name as shown in data.cart_items.",
    "update_quantity": "Change the quantity of an item already in the cart. Only available on the cart screen.",
    "checkout": "Go to the checkout screen to review the order.",
    "apply_promo": "Apply a promo or discount code to the order.",
    "place_order": "Place the order.",
    "update_address": "Set the delivery address.",
    "select_store": "Choose the store to shop from. Later searches and cart actions use that store.",
    "select_delivery_window": "Choose a delivery time window.",
    "next_page": "Go to the next page of results.",
    "prev_page": "Go to the previous page of results.",
    "go_back": "Go back to the previous section of the site.",
}

DEFAULT_PARAM_DESCRIPTIONS = {
    "item": "Product name, or a distinctive part of it, exactly as shown in the last response",
    "query": "Search terms",
    "quantity": "New quantity",
    "code": "Promo or discount code",
    "address": "Full delivery address",
    "store": "Store name as shown on the site",
}

_JSON_TYPES = {"string", "integer", "number", "boolean"}


def _param_schema(name: str, spec: Any) -> dict[str, Any]:
    spec = spec if isinstance(spec, dict) else {}
    json_type = spec.get("type") if spec.get("type") in _JSON_TYPES else "string"
    schema: dict[str, Any] = {"type": json_type}
    description = spec.get("description") or DEFAULT_PARAM_DESCRIPTIONS.get(name)
    if description:
        schema["description"] = description
    if "enum" in spec and isinstance(spec["enum"], list):
        schema["enum"] = list(spec["enum"])
    return schema


def _is_required(spec: Any) -> bool:
    # The March seeds rarely say "required"; a param is required unless it says
    # otherwise or has a default.
    spec = spec if isinstance(spec, dict) else {}
    if "default" in spec:
        return False
    return spec.get("required", True) is not False


def action_tool(mapping: Mapping, name: str) -> dict[str, Any]:
    action = mapping.actions[name]
    params = action.get("params") or {}
    properties = {p: _param_schema(p, spec) for p, spec in params.items()}
    required = [p for p, spec in params.items() if _is_required(spec)]
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    description = (
        action.get("description")
        or DEFAULT_DESCRIPTIONS.get(name)
        or f"Run the '{name}' action of the {mapping.domain} site mapping."
    )
    return {"name": name, "description": description, "inputSchema": schema}


def build_tools(mapping: Mapping) -> list[dict[str, Any]]:
    """MCP-style tool list: start_session, the mapping's actions (sorted), close_session."""
    tools = [dict(START_SESSION)]
    tools.extend(action_tool(mapping, name) for name in sorted(mapping.actions))
    tools.append(dict(CLOSE_SESSION))
    return tools


def to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MCP-style tools -> Messages API tool definitions."""
    return [
        {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}}}
        for t in tools
    ]


def param_defaults(mapping: Mapping, name: str) -> dict[str, Any]:
    params = mapping.actions.get(name, {}).get("params") or {}
    return {p: spec["default"] for p, spec in params.items() if isinstance(spec, dict) and "default" in spec}
