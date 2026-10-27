"""server/mappings/amazon.json: its schema, tools and screens, the actions run on a local stand-in for
the pages they read (tests/amazon_shop.py, no network), and bot checks: a human-verification page
fails the call with "blocked by a bot check" and nothing on it is clicked or submitted."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from rindler_local import (
    LocalRindlerHost,
    MappingError,
    ScreenMatcher,
    build_tools,
    find_mapping_for_url,
    interpolate,
    load_mapping,
    validate_mapping,
)
from rindler_local.interpreter import BOT_CHECK_MESSAGE, bot_check_on_page

from tests.amazon_shop import AmazonShop, local_amazon_mapping


def _no_chromium_reason() -> str | None:
    """Why these tests cannot drive a Chromium here (none installed, or it cannot start), or None."""
    try:
        from browser_env import chromium_problem
    except ImportError as exc:
        return f"browser_env cannot be imported: {exc}"
    return chromium_problem()


_NO_CHROMIUM = _no_chromium_reason()
browser = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=f"no Chromium that starts: {_NO_CHROMIUM}")

AMAZON = load_mapping("amazon")


# the mapping itself


def test_amazon_mapping_is_valid_and_covers_amazon_urls():
    assert validate_mapping(AMAZON.raw) == []
    assert AMAZON.site_id == "amazon" and AMAZON.domain == "amazon.com"
    for url in ("https://www.amazon.com", "https://amazon.com/", "https://www.amazon.com/s?k=cable"):
        assert find_mapping_for_url(url).site_id == "amazon"
    assert find_mapping_for_url("https://www.notamazon.com/") is None


def test_tools_are_the_amazon_actions():
    tools = {t["name"]: t for t in build_tools(AMAZON)}
    assert sorted(tools) == sorted(["start_session", "close_session", "search_products", "open_product",
                                    "choose_format", "add_to_cart", "view_cart"])
    assert tools["search_products"]["inputSchema"]["required"] == ["query"]
    assert tools["open_product"]["inputSchema"]["required"] == ["item"]
    assert tools["choose_format"]["inputSchema"]["required"] == ["format"]
    assert "required" not in tools["add_to_cart"]["inputSchema"]


@pytest.mark.parametrize("url,screen", [
    ("https://www.amazon.com/", "home"),
    ("https://www.amazon.com/?ref_=nav_logo", "home"),
    ("https://www.amazon.com/s?k=usb-c+to+usb-c+cable", "search_results"),
    ("https://www.amazon.com/Anker-Charging-Cable/dp/B088NRLMPV/ref=sr_1_3?dib=x", "product"),
    ("https://www.amazon.com/dp/1847941842", "product"),
    ("https://www.amazon.com/gp/product/B088NRLMPV/ref=ox_sc_act_title_1?psc=1", "product"),
    ("https://www.amazon.com/cart/smart-wagon?newItems=d456,1&ref_=sw_refresh", "added_to_cart"),
    ("https://www.amazon.com/gp/cart/view.html?ref_=nav_cart", "cart"),
    ("https://www.amazon.com/cart?ref_=sw_gtc", "cart"),
    ("https://www.amazon.com/errors/validateCaptcha", "unknown"),
])
def test_screens_by_url(url, screen):
    assert ScreenMatcher(AMAZON.screens).detect(url) == screen


def _steps(mapping):
    for name, action in mapping.actions.items():
        for step in action["steps"]:
            yield f"action {name}", step
    for i, handler in enumerate(mapping.interrupt_handlers):
        yield f"interrupt handler {i}", {"action": "detect", "selector": handler["detect"]}
        for step in handler["dismiss"]:
            yield f"interrupt handler {i}", step


def test_no_step_buys_signs_in_runs_a_script_or_touches_a_bot_check():
    forbidden = ("buy-now", "checkout", "signin", "sign-in", "add-to-cart-ubb", "captchacharacters", "awswaf",
                 "human", "robot", "puzzle")
    for where, step in _steps(AMAZON):
        assert step["action"] != "script", f"{where} runs a script"
        targets = [step.get("selector") or "", step.get("url") or ""]
        targets += [fb["selector"] for fb in step.get("fallbacks") or []]
        for target in targets:
            assert target not in AMAZON.bot_checks, f"{where} uses bot-check selector {target!r}"
            for word in forbidden:
                assert word not in target.lower(), f"{where} mentions {word!r}: {target!r}"


def test_search_query_goes_into_the_url_encoded():
    url = AMAZON.actions["search_products"]["steps"][0]["url"]
    assert interpolate(url, {"query": "USB-C to USB-C & more #1"}) == \
        "https://www.amazon.com/s?k=USB-C+to+USB-C+%26+more+%231"


def test_bot_checks_aria_extraction_and_extractor_lines_are_validated():
    base = {"domain": "x.com", "screens": {"a": {}}, "actions": {"go": {"steps": []}}}
    assert "bot_checks must be a list of selectors" in validate_mapping({**base, "bot_checks": "#captcha"})
    assert "bot_checks must be a list of selectors" in validate_mapping({**base, "bot_checks": ["#ok", ""]})
    assert "aria_extraction must be true or false" in validate_mapping({**base, "aria_extraction": "no"})
    assert "page_extractor must be a string of JavaScript or a list of its lines" in \
        validate_mapping({**base, "page_extractor": ["() => 1", 2]})
    with pytest.raises(MappingError):
        load_mapping({**base, "bot_checks": [1]})
    mapping = load_mapping({**base, "page_extractor": ["() => {", "  return 1;", "}"]})
    assert mapping.page_extractor == "() => {\n  return 1;\n}"
    assert mapping.bot_checks == [] and mapping.aria_extraction is True
    assert AMAZON.aria_extraction is False and AMAZON.bot_checks


# on the local stand-in (a real headless Chromium, no network)


@pytest.fixture
def shop():
    with AmazonShop() as running:
        yield running


def _blocked(env: dict) -> bool:
    error = env.get("error") or {}
    return error.get("code") == "bot_check" and error.get("message") == BOT_CHECK_MESSAGE


def _host(shop: AmazonShop, **changes) -> LocalRindlerHost:
    return LocalRindlerHost(local_amazon_mapping(shop.base, **changes), headless=True)


@browser
async def test_search_open_add_and_view_the_cart(shop):
    host = _host(shop)
    try:
        env = await host.call("start_session", {"url": shop.base + "/"})
        assert env["screen"] == "home" and env["data"]["page_info"] == {"page": "home"}

        env = await host.call("search_products", {"query": "usb-c to usb-c cable"})
        assert "error" not in env, env
        assert "/s?k=usb-c+to+usb-c+cable" in shop.requests
        assert env["screen"] == "search_results" and "products" not in env["data"]  # no generic ARIA lists
        results = env["data"]["page_info"]["results"]
        assert results[0] == {"position": 1, "title": "Braided USB C Cable 10ft", "price": "$12.99",
                              "rating": "4.7 out of 5 stars", "sponsored": True, "asin": "B0SPONSOR1"}
        assert results[1]["price"] == "$9.99" and "sponsored" not in results[1]  # the per-count price is skipped
        assert results[2]["formats"] == [{"format": "Kindle", "price": "$12.99"},
                                         {"format": "Paperback", "price": "$20.99"}, {"format": "Audio CD"}]
        assert "price" not in results[2]

        env = await host.call("open_product", {"item": "2"})  # by position
        assert "error" not in env, env
        info = env["data"]["page_info"]
        assert env["screen"] == "product" and info["asin"] == "B0CABLE002"
        assert info["price"] == "$9.99" and info["can_add_to_cart"] is True

        env = await host.call("add_to_cart", {})
        assert "error" not in env, env
        assert env["screen"] == "added_to_cart" and env["context"]["cart_count"] == "1"
        assert env["data"]["page_info"] == {"page": "added_to_cart", "message": "Added to cart", "cart_count": "1"}
        assert shop.amazon_cart == {"B0CABLE002": 1}

        env = await host.call("search_products", {"query": "atomic habits"})
        env = await host.call("open_product", {"item": "Atomic Habits"})  # by title
        info = env["data"]["page_info"]
        assert info["format"] == "Kindle" and info["can_add_to_cart"] is False
        env = await host.call("add_to_cart", {})
        assert env["error"]["code"] == "execution_failed"  # no Add to cart button on a Kindle page

        env = await host.call("choose_format", {"format": "Paperback"})
        assert "error" not in env, env
        info = env["data"]["page_info"]
        assert info["format"] == "Paperback" and info["price"] == "$20.99" and info["asin"] == "1847941842"
        await host.call("add_to_cart", {})

        env = await host.call("view_cart", {})
        assert env["screen"] == "cart"
        assert env["data"]["page_info"] == {
            "page": "cart",
            "cart_items": [
                {"title": "Anker USB C to USB C Cable, 60W Fast Charging (2-Pack, 6 ft)", "price": "$9.99",
                 "quantity": 1, "asin": "B0CABLE002"},
                {"title": "Atomic Habits", "price": "$20.99", "quantity": 1, "asin": "1847941842",
                 "format": "Paperback"},
            ],
            "subtotal": "$30.98",
            "subtotal_label": "Subtotal (2 items):",
            "empty": False,
        }
        assert "buy-now" not in shop.hits
    finally:
        await host.close()


@browser
async def test_the_continue_shopping_page_is_clicked_through_each_time(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        shop.interpose["/s"] = ["continue"]
        env = await host.call("search_products", {"query": "cable"})
        assert "error" not in env, env
        assert shop.hits == {"/errors_page/validateCaptcha": 1}
        assert env["screen"] == "search_results" and env["data"]["page_info"]["results"]

        shop.interpose["/gp/cart/view.html"] = ["continue"]  # again, later in the same session
        env = await host.call("view_cart", {})
        assert "error" not in env, env
        assert shop.hits == {"/errors_page/validateCaptcha": 2}
        assert env["data"]["page_info"]["page"] == "cart"
    finally:
        await host.close()


@browser
async def test_a_captcha_behind_the_continue_shopping_page_fails_the_call(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        shop.interpose["/s"] = ["continue", "captcha"]
        started = time.monotonic()
        env = await host.call("search_products", {"query": "cable"})
        assert _blocked(env)
        assert shop.hits == {"/errors_page/validateCaptcha": 1}  # the Continue button, never the captcha form
        # The handler's own wait (10 s) stops when the captcha shows instead of running out on it.
        assert time.monotonic() - started < 8
    finally:
        await host.close()


@browser
async def test_a_wait_stops_when_a_bot_check_shows_up(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        shop.interpose["/gp/cart/view.html"] = ["late-captcha"]  # a captcha one second after the page loads
        started = time.monotonic()
        env = await host.call("view_cart", {})  # waits up to 15 s for the cart
        assert _blocked(env)
        assert time.monotonic() - started < 8
        assert shop.hits == {}
    finally:
        await host.close()


@browser
async def test_amazon_bot_checks_tell_the_pages_apart(shop):
    host = _host(shop)
    detect = AMAZON.interrupt_handlers[0]["detect"]
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        page = host.page
        for path, is_bot_check, is_continue in [
            ("/special/captcha", True, False),
            ("/special/human", True, False),
            ("/special/continue", False, True),
            ("/special/checkpoint", True, False),
            ("/special/human-checkpoint", True, False),
            ("/special/late-captcha", False, False),  # not up yet
            ("/special/sign-in", True, False),
            ("/special/check-the-box", True, False),
            ("/s", False, False),
            ("/Anker-Cable/dp/B0CABLE002", False, False),
            ("/gp/cart/view.html", False, False),
        ]:
            await page.goto(shop.base + path)
            found = await bot_check_on_page(page, AMAZON.bot_checks)
            assert (found is not None) == is_bot_check, (path, found)
            assert (await page.locator(detect).count() == 1) == is_continue, path
        assert shop.hits == {}
    finally:
        await host.close()


@browser
@pytest.mark.parametrize("page_name", ["captcha", "human"])
async def test_a_bot_check_at_the_start_fails_the_session(shop, page_name):
    host = _host(shop)
    try:
        env = await host.call("start_session", {"url": f"{shop.base}/special/{page_name}"})
        assert _blocked(env)
        assert env["error"]["matched"] in AMAZON.bot_checks
        assert env["error"]["page_url"] == f"{shop.base}/special/{page_name}"
        assert host.session_id is None
        assert shop.hits == {}
    finally:
        await host.close()


@browser
@pytest.mark.parametrize("action,path,page_name", [
    ("search_products", "/s", "captcha"),
    ("view_cart", "/gp/cart/view.html", "human"),
    ("search_products", "/s", "human-checkpoint"),
    ("view_cart", "/gp/cart/view.html", "sign-in"),
    ("view_cart", "/gp/cart/view.html", "check-the-box"),
])
async def test_a_bot_check_during_an_action_fails_it_and_is_left_alone(shop, action, path, page_name):
    # A handler that would click any "Continue shopping" button: the captcha page has one, and only
    # the bot check, looked for first, keeps it from being pressed.
    greedy = {"detect": 'button:has-text("Continue shopping")',
              "dismiss": [{"action": "click", "selector": 'button:has-text("Continue shopping")'}]}
    host = _host(shop, interrupt_handlers=[greedy])
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        shop.interpose[path] = [page_name]
        env = await host.call(action, {"query": "cable"} if action == "search_products" else {})
        assert _blocked(env)
        assert shop.hits == {}
    finally:
        await host.close()


@browser
async def test_the_checkpoint_page_ends_the_session_untouched(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        shop.interpose["/s"] = ["checkpoint"]
        env = await host.call("search_products", {"query": "cable"})
        assert _blocked(env)
        assert env["error"]["matched"] == "#tmms-challenge"
        assert env["error"]["page_url"].startswith(shop.base + "/s?k=cable")
        assert shop.hits == {}  # its Continue shopping button was not pressed
        assert host.session_id is None and host.blocked

        # The run cannot try its way past: every later action gets the same answer.
        for name, args in (("search_products", {"query": "cable"}), ("view_cart", {})):
            env = await host.call(name, args)
            assert _blocked(env)
        assert shop.hits == {}

        env = await host.call("start_session", {"url": shop.base + "/"})  # a new session starts clean
        assert "error" not in env and not host.blocked
    finally:
        await host.close()


@browser
async def test_a_checkpoint_after_a_click_fails_at_once(shop):
    host = _host(shop)
    try:
        await host.call("start_session", {"url": shop.base + "/"})
        await host.call("search_products", {"query": "cable"})
        shop.interpose["/Anker-Cable/dp/B0CABLE002"] = ["checkpoint"]
        started = time.monotonic()
        env = await host.call("open_product", {"item": "2"})  # then waits up to 15 s for the product title
        assert _blocked(env) and env["error"]["matched"] == "#tmms-challenge"
        assert time.monotonic() - started < 8
        assert shop.hits == {}
    finally:
        await host.close()


@browser
async def test_a_bot_check_that_appears_later_stops_the_next_click_even_an_optional_one(shop):
    poke = {"steps": [{"action": "click", "selector": "button", "optional": True, "timeout": 500}]}
    raw_actions = json.loads(json.dumps(local_amazon_mapping("http://x").raw["actions"]))
    host = _host(shop, actions={**raw_actions, "poke": poke})
    try:
        env = await host.call("start_session", {"url": shop.base + "/special/late-captcha"})
        assert "error" not in env, env  # the captcha is not up yet
        await asyncio.sleep(1.5)
        env = await host.call("poke", {})
        assert _blocked(env)
        assert shop.hits == {}
    finally:
        await host.close()
