"""rindler_local: mapping loading, tool schemas, screen detection, extraction, and the
interpreter driving a real headless Chromium against a local fixture shop (no network)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from rindler_local import (
    LocalRindlerHost,
    MappingError,
    ScreenMatcher,
    build_tools,
    extract_cart_items,
    extract_products,
    find_mapping_for_url,
    interpolate,
    load_mapping,
    parse_result,
    to_anthropic,
    validate_mapping,
)
from rindler_local.mapping import MAPPINGS_DIR, domain_matches, slugify

from tests.fixture_shop import MAPPING_PATH, FixtureShop


# ---------------------------------------------------------------------------
# mapping basics
# ---------------------------------------------------------------------------


def test_interpolate_replaces_known_and_keeps_unknown():
    assert interpolate("q={{query}}&s={{store_slug}}", {"query": "chain belt"}) == "q=chain belt&s={{store_slug}}"
    assert interpolate("{{ n }}/{{flag}}/{{f}}", {"n": 3, "flag": True, "f": 2.0}) == "3/true/2"
    assert interpolate("/shop/{{store:slug}}", {"store": "Smart & Final"}) == "/shop/smart-final"
    assert interpolate("{{x:nosuchfilter}}", {"x": "a"}) == "{{x:nosuchfilter}}"
    assert slugify("Target") == "target"


def test_domain_matching():
    assert domain_matches("www.shipt.com", "shipt.com")
    assert domain_matches("shipt.com", "shipt.com")
    assert not domain_matches("notshipt.com", "shipt.com")
    assert not domain_matches("", "shipt.com")


def test_committed_mappings_load_and_validate():
    for site in ("vhlistings", "shipt"):
        mapping = load_mapping(site)
        assert mapping.site_id == site
        assert validate_mapping(mapping.raw) == []
    assert find_mapping_for_url("https://www.shipt.com/shop").site_id == "shipt"
    assert find_mapping_for_url("https://vhlistings.com/").site_id == "vhlistings"
    assert find_mapping_for_url("https://example.org/") is None


def test_validate_mapping_reports_each_problem():
    bad = {
        "domain": "x.com",
        "screens": {"home": {"url_pattern": "(", "available_actions": ["missing_action"]}},
        "actions": {
            "done": {"steps": []},
            "go": {"target_screen": "nowhere", "steps": [{"action": "teleport"}, {"action": "click"}]},
            "wait_bad": {"steps": [{"action": "wait", "strategy": "selector_visible"}, {"action": "navigate"}]},
            "fb": {"steps": [{"action": "click", "selector": "a", "fallbacks": [{"type": "sonar", "selector": "a"}]}]},
        },
    }
    problems = "\n".join(validate_mapping(bad))
    for expected in (
        "bad url_pattern",
        "available action 'missing_action' is not defined",
        "action name 'done' is reserved",
        "target_screen 'nowhere'",
        "unknown action 'teleport'",
        "click needs a selector",
        "selector_visible needs a selector",
        "navigate needs a url",
        "fallback 0",
    ):
        assert expected in problems
    with pytest.raises(MappingError):
        load_mapping(bad)
    with pytest.raises(MappingError, match="known sites"):
        load_mapping("no_such_site")


def test_page_extractor_override_from_file(tmp_path):
    js = tmp_path / "extract.js"
    js.write_text("() => ({ok: true})")
    mapping = load_mapping("vhlistings", page_extractor=js)
    assert mapping.page_extractor == "() => ({ok: true})"


# ---------------------------------------------------------------------------
# tool schemas
# ---------------------------------------------------------------------------


def test_tools_are_exactly_the_mapping_actions_plus_session_tools():
    mapping = load_mapping("vhlistings")
    tools = build_tools(mapping)
    names = [t["name"] for t in tools]
    assert names[0] == "start_session" and names[-1] == "close_session"
    assert sorted(names[1:-1]) == sorted(mapping.actions)
    # Tools the March server always listed but vhlistings never defined do not appear.
    for absent in ("update_address", "select_store", "place_order", "summarize_page", "book_demo"):
        assert absent not in names

    by_name = {t["name"]: t for t in tools}
    assert by_name["start_session"]["inputSchema"]["required"] == ["url"]
    search = by_name["search_products"]["inputSchema"]
    assert search["properties"]["query"]["type"] == "string" and search["required"] == ["query"]
    assert "required" not in by_name["add_to_cart"]["inputSchema"]
    assert "session_id" not in json.dumps(tools)
    # The mapping's own description is used verbatim.
    assert by_name["apply_promo"]["description"] == mapping.actions["apply_promo"]["description"]

    anthropic_tools = to_anthropic(tools)
    assert all(set(t) == {"name", "description", "input_schema"} for t in anthropic_tools)


def test_tools_fall_back_to_default_descriptions_and_optional_params():
    shipt = {t["name"]: t for t in build_tools(load_mapping("shipt"))}
    assert "update_address" in shipt and "select_store" in shipt
    assert shipt["view_cart"]["description"].startswith("Open the cart")
    assert shipt["update_quantity"]["inputSchema"]["required"] == ["item", "quantity"]

    fixture = {t["name"]: t for t in build_tools(load_mapping(MAPPING_PATH))}
    assert "required" not in fixture["sort_results"]["inputSchema"]  # has a default
    assert fixture["flaky_action"]["description"] == "Run the 'flaky_action' action of the 127.0.0.1 site mapping."


# ---------------------------------------------------------------------------
# screens and extraction
# ---------------------------------------------------------------------------


def test_screen_matcher_tries_longest_pattern_first():
    screens = {
        "shop": {"url_pattern": r"shipt\.com/shop"},
        "cart": {"url_pattern": r"shipt\.com/shop/cart"},
        "landing": {"url_pattern": r"shipt\.com/$"},
        "no_pattern": {},
    }
    matcher = ScreenMatcher(screens)
    assert matcher.detect("https://www.shipt.com/shop/cart") == "cart"
    assert matcher.detect("https://www.shipt.com/shop") == "shop"
    assert matcher.detect("https://www.shipt.com/") == "landing"
    assert matcher.detect("https://example.com/") == "unknown"
    assert matcher.detect("https://example.com/", fallback="search_results") == "search_results"


SNAPSHOT_SHOPIFY = """- main:
  - list:
    - listitem:
      - text: SAVE $15
      - heading "Gravechain Crucifix Belt 22%" [level=3]:
        - link "Gravechain Crucifix Belt 22%":
          - /url: /products/gravechain
      - text: Regular price $52.00 Sale price $67.00
    - listitem:
      - heading [level=3]:
        - link "https://cdn.example.com/img.jpg"
        - link "Iron Thorn Wallet Chain™":
      - text: $29.00
    - listitem:
      - heading "https://cdn.example.com/x.png" [level=3]
    - listitem:
      - heading "$99/year" [level=3]
      - heading "$3" [level=3]
"""

SNAPSHOT_GRID = """- list:
  - listitem:
    - text: $3.99
    - button "Add 1, Fresh Gala Apple - 3lb Bag, to cart"
  - listitem:
    - button "Add 1 Whole Milk 1gal to cart"
"""

SNAPSHOT_CART = """- main:
  - list:
    - listitem:
      - text: Skeleton Fishbone Wallet Chain
      - text: $32.00
      - text: "Qty: 2"
      - link "Remove Skeleton Fishbone Wallet Chain":
    - listitem:
      - button "Remove Organic Bananas from Cart"
      - combobox "Quantity for Organic Bananas" [value="3"]
      - text: $1.99
"""


def test_extract_products_from_shopify_headings():
    products = extract_products(SNAPSHOT_SHOPIFY)
    assert products[0] == {
        "name": "Gravechain Crucifix Belt",
        "price": "$52.00",
        "price_text": "Regular price $52.00 Sale price $67.00",
    }
    assert products[1] == {"name": "Iron Thorn Wallet Chain", "price": "$29.00"}
    assert len(products) == 2  # image-URL and price-only headings are skipped


def test_extract_products_from_add_buttons():
    products = extract_products(SNAPSHOT_GRID)
    assert products[0] == {"name": "Fresh Gala Apple - 3lb Bag", "price": "$3.99", "size": "3lb"}
    assert products[1]["name"] == "Whole Milk 1gal" and products[1]["size"] == "1gal"


def test_extract_cart_items():
    items = extract_cart_items(SNAPSHOT_CART)
    assert items[0] == {"name": "Skeleton Fishbone Wallet Chain", "price": "$32.00", "quantity": "2"}
    assert items[1]["name"] == "Organic Bananas" and items[1]["quantity"] == "3"
    assert extract_cart_items("") == [] and extract_products("") == []


# ---------------------------------------------------------------------------
# the interpreter on a real browser
# ---------------------------------------------------------------------------


def _no_chromium_reason() -> str | None:
    """Why these tests cannot drive a Chromium here (none installed, or it cannot start), or None."""
    try:
        from browser_env import chromium_problem
    except ImportError as exc:
        return f"browser_env cannot be imported: {exc}"
    return chromium_problem()


_NO_CHROMIUM = _no_chromium_reason()
browser = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=f"no Chromium that starts: {_NO_CHROMIUM}")


@pytest.fixture
def shop():
    with FixtureShop() as running:
        yield running


def _host(shop: FixtureShop, **kwargs) -> LocalRindlerHost:
    raw = json.loads(MAPPING_PATH.read_text())
    raw["defaults"]["base"] = shop.base
    return LocalRindlerHost(load_mapping(raw), headless=True, **kwargs)


async def test_a_chromium_that_cannot_start_comes_back_as_a_readable_tool_error(shop, tmp_path):
    chrome = tmp_path / "chrome"
    chrome.write_text('#!/bin/sh\necho "$0: error while loading shared libraries: libnspr4.so: '
                      'cannot open shared object file: No such file or directory" >&2\nexit 127\n')
    chrome.chmod(0o755)
    host = _host(shop, executable_path=str(chrome))
    try:
        env = await host.call("start_session", {"url": shop.base + "/"})
    finally:
        await host.close()
    assert env["error"]["code"] == "internal_error"
    assert "libnspr4.so" in env["error"]["message"]
    assert "playwright install-deps chromium" in env["error"]["message"]


@browser
async def test_session_lifecycle_and_errors(shop):
    host = _host(shop)
    try:
        env = await host.call("search_products", {"query": "belt"})
        assert env["error"]["code"] == "no_session"

        env = await host.call("start_session", {"url": "https://example.org/"})
        assert env["error"]["code"] == "no_site_config"
        env = await host.call("start_session", {"url": "file:///etc/hosts"})
        assert env["error"]["code"] == "invalid_url"

        env = await host.call("start_session", {"url": shop.base + "/"})
        assert "error" not in env
        assert env["screen"] == "landing"
        assert env["data"]["session_id"] and env["data"]["page_url"] == shop.base + "/"
        assert env["available_actions"] == ["search_products", "search_with_form", "sort_results", "view_cart"]
        assert env["global_actions"] == ["start_session"]
        assert env["context"]["cart_count"] == "0"
        assert "never_there" not in env["context"]

        raw = await host.call_tool("add_to_cart", {})
        assert raw["isError"] is True
        env = parse_result(raw)
        assert env["error"]["code"] == "invalid_action" and "landing" in env["error"]["message"]

        env = await host.call("no_such_tool", {})
        assert env["error"]["code"] == "unknown_action"

        env = await host.call("close_session", {})
        assert env["data"] == {"closed": True}
        env = await host.call("view_cart", {})
        assert env["error"]["code"] == "no_session"
    finally:
        await host.close()
        await host.close()  # idempotent


@browser
async def test_shopping_flow_fallbacks_interrupts_context_and_page_info(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})

        # navigate + {{query}}; the popup shows ~300 ms after load and is dismissed.
        env = await host.call("search_products", {"query": "chain", "session_id": "ignored"})
        assert env["screen"] == "search_results"
        assert host.interrupts.dismissed == {'[aria-label="Close dialog"]'}
        assert shop.dismissals == 1
        names = [p["name"] for p in env["data"]["products"]]
        assert names == ["Iron Chain Belt", "Spike Wallet Chain"]  # "25%" badge stripped
        assert env["data"]["products"][0]["price"] == "$29.00"
        assert env["data"]["page_info"]["path"] == "/search"
        assert any(r.startswith("/search?q=chain") for r in shop.requests)

        # primary xpath matches nothing -> css fallback clicks the card; target_screen applies.
        env = await host.call("view_product", {"item": "Iron Chain Belt"})
        assert "error" not in env, env
        assert env["screen"] == "product_detail"
        assert env["data"]["page_url"].endswith("/products/iron-chain-belt")

        # stays_on_screen; the optional drawer-close click fails silently; context extractor updates.
        env = await host.call("add_to_cart", {})
        assert "error" not in env, env
        assert env["screen"] == "product_detail"
        assert shop.cart == {"iron-chain-belt": 1}
        assert env["context"]["cart_count"] == "1"

        # a non-optional failing step fails the action and names the step.
        env = await host.call("flaky_action", {})
        assert env["error"]["code"] == "execution_failed"
        assert env["error"]["message"].startswith("step 1 (click) failed")
        assert env["screen"] == "product_detail"

        env = await host.call("view_cart", {})
        assert env["screen"] == "cart"
        assert env["data"]["cart_items"] == [{"name": "Iron Chain Belt", "price": "$29.00", "quantity": "1"}]

        # no target_screen: the screen is re-detected from the URL after the redirect.
        env = await host.call("remove_from_cart", {"item": "Iron Chain Belt"})
        assert "error" not in env, env
        assert env["screen"] == "cart" and shop.cart == {}
        assert "cart_items" not in env["data"]

        env = await host.call("checkout", {})
        assert env["screen"] == "checkout", env

        env = await host.call("apply_promo", {"code": "SPRING"})
        assert env["data"]["extracted"] == {"promo_message": "Order discount applied"}
        # Every page showed the popup again, but a handler fires once per session.
        assert shop.dismissals == 1
    finally:
        await host.close()


@browser
async def test_type_select_press_key_script_and_text_fallback(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})

        env = await host.call("sort_results", {})  # param default "price"
        assert "error" not in env, env
        assert env["data"]["page_info"]["sorted"] == "sorted:price"  # select fired, script ran

        env = await host.call("search_with_form", {"query": "wallet"})  # placeholder fallback + Enter
        assert "error" not in env, env
        assert env["screen"] == "search_results"
        assert [p["name"] for p in env["data"]["products"]] == ["Spike Wallet Chain"]

        env = await host.call("view_product_by_text", {"item": "Spike Wallet Chain 25%"})
        assert "error" not in env, env
        assert env["screen"] == "product_detail"  # re-detected from the URL
    finally:
        await host.close()


def _descendants(pid: int) -> list[str]:
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    wanted, found, grew = {pid}, [], True
    while grew:
        grew = False
        for child, parent, command in rows:
            if parent in wanted and child not in wanted:
                wanted.add(child)
                found.append(command)
                grew = True
    return found


@browser
async def test_browser_runs_headless_with_keychain_flags(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        # The browser process itself; its renderer/GPU helpers carry --type=... and not the flags.
        browsers = [c for c in _descendants(os.getpid()) if "--remote-debugging-pipe" in c and "--type=" not in c]
        assert browsers, "expected the Playwright-launched Chromium among this test's child processes"
        for command in browsers:
            assert "--use-mock-keychain" in command
            assert "--password-store=basic" in command
            assert "--headless" in command
    finally:
        await host.close()
