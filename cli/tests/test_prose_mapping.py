"""The shipped prose mapping and page extractor against tests/prose_fixture.py.

The fixture follows prose.com as it was on 2026-10-24. Against that site the March
mapping and extractor had drifted, each way pinned here:

* the cart page fills in about a second after it loads, so view_cart returned before
  there was anything to read;
* cart line items are plain divs, not <p>, so cart_items came back empty;
* "Subtotal" and "Today's total" sit on separate lines (and the apostrophe is curly), so
  order_summary came back empty;
* the accessories grid showed a de-duplicated price list, so the three $85 brushes
  could not be told apart from the other prices;
* the grid's product cards render after the page's first h2, which is all the mapping waited for;
* the eye patches page has two add-to-cart buttons, which Playwright refuses to click;
* remove_from_cart clicked the first Remove button whatever item it was given.
"""

import pytest

from benchcli import sites
from prose_fixture import ProseShop, localize
from rindler_local import LocalRindlerHost


def _no_chromium_reason() -> str | None:
    """Why these tests cannot drive a Chromium here (none installed, or it cannot start), or None."""
    try:
        import browser_env

        return browser_env.chromium_problem()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


_NO_CHROMIUM = _no_chromium_reason()


pytestmark = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=f"no Chromium that starts: {_NO_CHROMIUM}")


@pytest.fixture(scope="module")
def shop():
    with ProseShop() as shop:
        yield shop


@pytest.fixture
async def host(shop):
    shop.cart.clear()
    mapping = localize(sites.load_site("prose").mapping, shop.base)
    async with LocalRindlerHost(mapping) as host:
        env = await host.call("start_session", {"url": shop.base})
        assert env["screen"] == "homepage", env
        yield host


def info(envelope):
    assert "error" not in envelope, envelope
    return envelope["data"]["page_info"]


async def test_view_cart_waits_for_the_cart_to_render(host):
    await host.call("view_accessories")
    await host.call("view_product", {"item": "Hair Towel Wrap"})
    await host.call("add_to_cart", {"item": "Hair Towel Wrap"})
    cart = info(await host.call("view_cart"))
    assert cart["title"] == "Your cart(1)"
    assert cart["cart_items"] == [{"name": "Hair Towel", "price": "$35.00", "quantity": "1"}]


async def test_cart_items_list_every_line(host):
    for item in ("Hair Towel Wrap", "Candle"):
        await host.call("view_accessories")
        await host.call("view_product", {"item": item})
        await host.call("add_to_cart", {"item": item})
    cart = info(await host.call("view_cart"))
    assert cart["title"] == "Your cart(2)"
    assert cart["cart_items"] == [
        {"name": "Hair Towel", "price": "$35.00", "quantity": "1"},
        {"name": "Arcadia Candle", "price": "$52.00", "quantity": "1"},
    ]


async def test_order_summary_reads_subtotal_shipping_and_total(host):
    await host.call("view_accessories")
    await host.call("view_product", {"item": "Candle"})
    await host.call("add_to_cart", {"item": "Candle"})
    summary = info(await host.call("view_cart"))["order_summary"]
    assert summary == {
        "subtotal": "Subtotal (1 item) $52.00",
        "shipping": "Shipping $6.95",
        "total": "Today’s total (pre-tax) $58.95",
    }


async def test_an_empty_cart_reads_as_empty(host):
    cart = info(await host.call("view_cart"))
    assert cart["title"] == "Your cart is empty (0)"
    assert "cart_items" not in cart
    assert cart["order_summary"]["subtotal"] == "Subtotal (0 item) $0.00"


async def add_two(host):
    for item in ("Hair Towel Wrap", "Candle"):
        await host.call("view_accessories")
        await host.call("view_product", {"item": item})
        await host.call("add_to_cart", {"item": item})
    await host.call("view_cart")


async def test_remove_from_cart_removes_the_named_line_not_the_first(host, shop):
    await add_two(host)
    removed = await host.call("remove_from_cart", {"item": "Candle"})  # the cart calls it "Arcadia Candle"
    assert "error" not in removed
    assert [i["cart_name"] for i in shop.cart] == ["Hair Towel"]
    cart = info(await host.call("view_cart"))
    assert cart["cart_items"] == [{"name": "Hair Towel", "price": "$35.00", "quantity": "1"}]
    assert (await host.call("remove_from_cart", {"item": "hair towel"}))["screen"] == "cart"  # case does not matter
    assert shop.cart == []


async def test_remove_from_cart_with_an_unknown_name_fails_and_removes_nothing(host, shop):
    await add_two(host)
    result = await host.call("remove_from_cart", {"item": "Boar Bristle Brush"})
    assert result["error"]["code"] == "execution_failed"
    assert len(shop.cart) == 2


async def test_the_accessories_page_pairs_each_product_with_its_price(host):
    page = info(await host.call("view_accessories"))
    assert page["title"] == "Accessories"
    assert page["product_cards"] == [
        {"name": "Reusable Eye Patches", "price": "$26.00"},
        {"name": "Hair Towel Wrap", "price": "$35.00"},
        {"name": "Candle", "price": "$52.00"},
        {"name": "Boar Bristle Brush", "price": "$85.00"},
        {"name": "Boar + Nylon Brush", "price": "$85.00"},
        {"name": "Tipped-Metal Brush", "price": "$85.00"},
        {"name": "Digital Gift Cards", "price": "From $50.00"},
    ]


async def test_add_to_cart_works_when_the_page_has_two_add_buttons(host, shop):
    await host.call("view_accessories")
    await host.call("view_product", {"item": "Reusable Eye Patches"})
    added = await host.call("add_to_cart", {"item": "Reusable Eye Patches"})
    assert "error" not in added, added
    assert [i["cart_name"] for i in shop.cart] == ["Eye Patches"]  # one click, one unit


async def test_a_product_page_has_no_product_cards(host):
    await host.call("view_accessories")
    page = info(await host.call("view_product", {"item": "Hair Towel Wrap"}))
    assert page["title"] == "Hair Towel Wrap" and "product_cards" not in page
    assert page["buttons"].count("ADD TO CART") == 1


async def test_the_gift_page_has_something_to_read(host):
    page = info(await host.call("view_gift_cards"))
    assert page["main_text"].lower().startswith("digital gift card")  # the site navigation before it is cut off
    assert "Choose your gift amount" in page["main_text"] and "Skip to main content" not in page["main_text"]
