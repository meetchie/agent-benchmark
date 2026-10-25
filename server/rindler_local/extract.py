"""Product and cart-item lists read from a page's ARIA snapshot.

The Rindler server gave the model structured ``products`` / ``cart_items`` instead of
the raw page. This module does the same from Playwright's ``aria_snapshot()`` text with
a few site-agnostic heuristics:

* products: buttons named like "Add 1, <name>, to cart" (Shipt-style grids); failing
  that, level-3 headings (Shopify product cards) with the price on a nearby line.
* cart items: links/buttons named "Remove <name>" (optionally "... from cart"), with the
  price and quantity found on nearby lines.

The numbers are a convenience for the model, not ground truth; they can miss items on
sites with other markup.
"""

from __future__ import annotations

import re
from typing import Any

MAX_PRODUCTS = 40
MAX_CART_ITEMS = 40

_PRICE = re.compile(r"\$\d[\d,]*\.\d{2}")
_SIZE = re.compile(r"\b(\d+(?:\.\d+)?\s*(?:fl oz|gal|lbs?|oz|ct|count|pk|pack|ml|kg|g|L))\b", re.I)
_ADD_BUTTON = re.compile(r'-\s+button\s+"Add\s+1[,\s]+(.+?)[,\s]+to\s+cart"', re.I)
_HEADING3 = re.compile(r'-\s+heading\s+"([^"]+)"\s+\[level=3\]')
_HEADING3_BARE = re.compile(r"-\s+heading\s+\[level=3\]")
_CHILD_LINK = re.compile(r'-\s+link\s+"([^"]+)"')
_CHILD_TEXT = re.compile(r"^\s*-\s+text:\s+(.+)$")
_BADGE = re.compile(r"\s+-?\d{1,3}%(?:\s*off)?$", re.I)
_REMOVE = re.compile(r'^\s*-\s+(?:link|button)\s+"Remove\s+(.+?)(?:\s+from\s+cart)?"', re.I)
_QTY = re.compile(r"(?:qty[:\s]*|quantity[:\s]*|×\s*)(\d+)", re.I)
_VALUE = re.compile(r'(?:spinbutton|combobox|textbox)\s+"[^"]*[Qq]uantity[^"]*"[^:\n]*:\s*"?(\d+)"?|\[value="(\d+)"\]')
_JUNK_CHARS = dict.fromkeys(map(ord, "™®©℠ⓘ"), None)


_PRICE_ONLY = re.compile(r"^\$\s?[\d.,]+(?:\s*/\s*\w+)?$")


def _clean(name: str) -> str:
    name = name.translate(_JUNK_CHARS)
    name = _BADGE.sub("", name.strip())
    name = re.sub(r"\s+", " ", name).strip()
    # A heading that is only a price ("$1", "$99/year") is a promo tile, not a product.
    return "" if _PRICE_ONLY.match(name) else name


def _price_in(line: str) -> tuple[str | None, str | None]:
    found = _PRICE.findall(line)
    if not found:
        return None, None
    text = re.sub(r"^\s*-\s+(text:\s*)?", "", line).strip()
    return found[0], (text[:120] if len(found) > 1 else None)


def _price_after(lines: list[str], i: int, ahead: int = 8, behind: int = 2) -> tuple[str | None, str | None]:
    """Price for the card whose title is lines[i]: look below it first (up to the next
    card title), then just above it (not past the start of the card)."""
    for line in lines[i + 1:i + 1 + ahead]:
        if "[level=3]" in line:
            break
        price = _price_in(line)
        if price[0]:
            return price
    for j in range(i - 1, max(i - 1 - behind, -1), -1):
        if "listitem" in lines[j] or "[level=3]" in lines[j]:
            break
        price = _price_in(lines[j])
        if price[0]:
            return price
    return None, None


def _by_distance(lines: list[str], i: int, radius: int) -> list[str]:
    """lines around i, nearest first (i+1, i-1, i+2, i-2, ...)."""
    out = []
    for d in range(1, radius + 1):
        for j in (i + d, i - d):
            if 0 <= j < len(lines):
                out.append(lines[j])
    return out


def extract_products(snapshot: str) -> list[dict[str, Any]]:
    if not snapshot:
        return []
    lines = snapshot.splitlines()
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        match = _ADD_BUTTON.search(line)
        if not match:
            continue
        name = _clean(match.group(1))
        if not name or name in seen:
            continue
        seen.add(name)
        item: dict[str, Any] = {"name": name}
        price, price_text = None, None
        for j in range(i - 1, max(i - 4, -1), -1):
            price, price_text = _price_in(lines[j])
            if price:
                break
        if price:
            item["price"] = price
        if price_text:
            item["price_text"] = price_text
        size = _SIZE.search(name)
        if size:
            item["size"] = size.group(1)
        products.append(item)
    if products:
        return products[:MAX_PRODUCTS]

    for i, line in enumerate(lines):
        if "[level=3]" not in line:
            continue
        name = ""
        match = _HEADING3.search(line)
        if match and not match.group(1).startswith("http"):
            name = match.group(1)
        elif _HEADING3_BARE.search(line):
            for nxt in lines[i + 1:i + 9]:
                if "[level=" in nxt or "tabpanel" in nxt:
                    break
                link = _CHILD_LINK.search(nxt)
                if link and not link.group(1).startswith("http"):
                    name = link.group(1)
                    break
                text = _CHILD_TEXT.match(nxt)
                if text:
                    name = text.group(1)
                    break
        name = _clean(name)
        if not name or name in seen:
            continue
        seen.add(name)
        item = {"name": name}
        price, price_text = _price_after(lines, i)
        if price:
            item["price"] = price
        if price_text:
            item["price_text"] = price_text
        products.append(item)
    return products[:MAX_PRODUCTS]


def extract_cart_items(snapshot: str) -> list[dict[str, Any]]:
    if not snapshot:
        return []
    lines = snapshot.splitlines()
    items: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        match = _REMOVE.match(line)
        if not match:
            continue
        name = _clean(match.group(1))
        if not name:
            continue
        item: dict[str, Any] = {"name": name}
        nearby = _by_distance(lines, i, 6)
        for line in nearby:
            price, _ = _price_in(line)
            if price:
                item["price"] = price
                break
        for line in nearby:
            qty = _QTY.search(line) or _VALUE.search(line)
            if qty:
                item["quantity"] = next(g for g in qty.groups() if g)
                break
        size = _SIZE.search(name)
        if size:
            item["size"] = size.group(1)
        items.append(item)
    return items[:MAX_CART_ITEMS]
