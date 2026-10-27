"""A local stand-in for the amazon.com pages the amazon mapping reads, for tests with no network.

The markup copies only what server/mappings/amazon.json relies on, as the live site had it on
2026-10-26: the ids, data attributes and classes of the search results, product page, format
swatches, "Added to cart" page and cart. There are also the pages the mapping must handle: the
"Click the button below to continue shopping" page, which it may click through, and the pages it
must never touch: human-verification pages (a classic captcha, "I am human" checks, a captcha drawn
by a script), the /checkpoint/ page and the sign-in page. Every form submit and button press is
counted in ``hits``.

    with AmazonShop() as shop:
        mapping = local_amazon_mapping(shop.base)   # amazon.json pointed at this server
        shop.interpose["/s"] = ["continue"]         # the next /s request gets that page instead
"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote, urlencode

from rindler_local import load_mapping

from tests.fixture_shop import FixtureShop

PRODUCTS = {
    "B0SPONSOR1": {"title": "Braided USB C Cable 10ft", "price": "12.99", "path": "/Braided-Cable/dp/B0SPONSOR1"},
    "B0CABLE002": {"title": "Anker USB C to USB C Cable, 60W Fast Charging (2-Pack, 6 ft)", "price": "9.99",
                   "path": "/Anker-Cable/dp/B0CABLE002"},
    "B07D23CFGR": {"title": "Atomic Habits", "price": "12.99", "path": "/Atomic-Habits-ebook/dp/B07D23CFGR",
                   "format": "Kindle"},
    "1847941842": {"title": "Atomic Habits", "price": "20.99", "path": "/Atomic-Habits-Paperback/dp/1847941842",
                   "format": "Paperback"},
}
BOOK_FORMATS = ("B07D23CFGR", "1847941842")

NAVBAR = '<div id="navbar"><a id="nav-cart" href="/gp/cart/view.html">Cart <span id="nav-cart-count">{count}</span></a></div>'


def _doc(body: str, *, nav: bool = True) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>Amazon.com</title></head><body>'
            f'{NAVBAR if nav else ""}<main>{body}</main></body></html>')


CONTINUE_PAGE = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<h4>Click the button below to continue shopping</h4>
<form method="get" action="/errors_page/validateCaptcha">
<input type="hidden" name="amzn" value="x"><input type="hidden" name="amzn-r" value="{back}">
<button type="submit" class="a-button-text">Continue shopping</button></form></body></html>"""

# The classic captcha page. Its submit button also reads "Continue shopping".
CAPTCHA_PAGE = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<h4>Enter the characters you see below</h4><p>Sorry, we just need to make sure you're not a robot.</p>
<form method="get" action="/errors/validateCaptcha">
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="200" height="70" alt="">
<input id="captchacharacters" name="field-keywords" type="text">
<button type="submit">Continue shopping</button></form></body></html>"""

# /checkpoint/continue: the normal header, then one "Continue shopping" button.
CHECKPOINT_PAGE = _doc("""<div id="tmms-challenge">
<h4>To continue, please click the "Continue shopping" button below.</h4>
<form method="POST" action="/checkpoint/validate?amzn-r={back_q}" id="checkpointForm"><input type="hidden" name="token" value="x">
<button type="submit" name="continueClick" value="true">Continue shopping</button></form></div>""")

# A check box page, as browser-use described one it met on 2026-10-26 (its markup is a guess).
CHECK_THE_BOX_PAGE = _doc("""<h4>Check the box to continue</h4>
<div><input type="checkbox" id="cb" onclick="fetch('/api/hit?name=checkbox')"><span>I am human</span></div>""")

# The same place asking for a human check (a guess at what it may show).
HUMAN_CHECKPOINT_PAGE = _doc("""<div id="tmms-challenge">
<h4>Let's confirm you are human</h4>
<form method="POST" action="/checkpoint/validate?amzn-r={back_q}" id="checkpointForm"><input type="hidden" name="token" value="x">
<input type="checkbox" id="human" onclick="fetch('/api/hit?name=checkbox')"><label for="human">I am human</label>
<button type="submit" name="continueClick" value="true">Continue shopping</button></form></div>""")

SIGN_IN_PAGE = """<!doctype html><html><head><title>Amazon Sign-In</title></head><body>
<h1>Sign in or create account</h1>
<form name="signIn" method="get" action="/api/hit"><input type="hidden" name="name" value="sign-in">
<input type="email" name="email" id="ap_email_login"><input type="submit" id="continue" value="Continue"></form></body></html>"""

HUMAN_PAGE = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<h1>Let's confirm you are human</h1><p>Complete the check to continue.</p>
<button onclick="fetch('/api/hit?name=i-am-human')">I am human</button></body></html>"""

# A captcha that a script puts up after the page has loaded, over the normal page.
LATE_CAPTCHA_PAGE = _doc("""<h1>One moment</h1>
<script>setTimeout(function(){document.querySelector('main').innerHTML='<div id="captcha-container">'
+ '<p>Solve the puzzle</p><button onclick="fetch(\\'/api/hit?name=puzzle\\')">Begin</button></div>';}, 1000);</script>""")

SPECIAL_PAGES = {
    "continue": CONTINUE_PAGE,
    "checkpoint": CHECKPOINT_PAGE,
    "captcha": CAPTCHA_PAGE,
    "human": HUMAN_PAGE,
    "human-checkpoint": HUMAN_CHECKPOINT_PAGE,
    "sign-in": SIGN_IN_PAGE,
    "check-the-box": CHECK_THE_BOX_PAGE,
    "late-captcha": LATE_CAPTCHA_PAGE,
}


def _special(name: str, back: str) -> str:
    """A SPECIAL_PAGES page whose Continue button leads back to ``back``."""
    page = SPECIAL_PAGES[name].replace("{back_q}", html.escape(quote(back, safe="")))
    return page.replace("{back}", html.escape(back))


def search_page() -> str:
    def result(asin: str, *, sponsored: bool = False, extra: str = "") -> str:
        p = PRODUCTS[asin]
        label = ("Sponsored Ad - " if sponsored else "") + p["title"]
        return (f'<div data-component-type="s-search-result" data-asin="{asin}">'
                f'<a class="a-link-normal s-link-style" href="{p["path"]}"><h2 aria-label="{html.escape(label)}">'
                f'<span>{html.escape(p["title"])}</span></h2></a>'
                f'<i class="a-icon a-icon-star-mini"><span class="a-icon-alt">4.7 out of 5 stars</span></i>{extra}</div>')

    def price(value: str) -> str:
        return f'<span class="a-price"><span class="a-offscreen">${value}</span></span>'

    book = ('<a href="/Atomic-Habits-ebook/dp/B07D23CFGR">Kindle</a>'
            f'<a aria-describedby="price-link" href="/Atomic-Habits-ebook/dp/B07D23CFGR">{price("12.99")}</a>'
            '<a href="/Atomic-Habits-Paperback/dp/1847941842">Paperback</a>'
            f'<a aria-describedby="price-link" href="/Atomic-Habits-Paperback/dp/1847941842">{price("20.99")}</a>'
            '<span>Other formats: </span><a href="/x">Audio CD</a>')
    return _doc(
        "<h1>Results</h1>"
        + result("B0SPONSOR1", sponsored=True, extra=price("12.99"))
        + result("B0CABLE002", extra=price("9.99") + '<span class="a-price a-text-price"><span class="a-offscreen">$5.00</span></span>')
        + result("B07D23CFGR", extra=book)
    )


def product_page(asin: str) -> str:
    p = PRODUCTS[asin]
    swatches = ""
    if asin in BOOK_FORMATS:
        cells = []
        for other in BOOK_FORMATS:
            o = PRODUCTS[other]
            selected = other == asin
            href = "javascript:void(0)" if selected else o["path"]
            cells.append(f'<div id="tmm-grid-swatch-{o["format"].upper()}" class="swatchElement {"selected" if selected else "unselected"}">'
                         f'<a href="{href}"><span class="slot-title">{o["format"]}</span>'
                         f'<span class="slot-price">${o["price"]}</span></a></div>')
        swatches = f'<div id="tmmSwatches">{"".join(cells)}</div>'
    buy = ""
    if p.get("format") != "Kindle":
        buy = (f'<form method="get" action="/cart/add-to-cart"><input type="hidden" name="ASIN" value="{asin}">'
               '<input id="add-to-cart-button" name="submit.add-to-cart" type="submit" value="Add to cart"></form>'
               '<form method="get" action="/api/hit"><input type="hidden" name="name" value="buy-now">'
               '<input id="buy-now-button" type="submit" value="Buy Now"></form>')
    return _doc(f'<span id="productTitle">{html.escape(p["title"])}</span>'
                f'<a id="bylineInfo" href="/x">Visit the Store</a>'
                f'<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">${p["price"]}</span></span></div>'
                f'{swatches}<div id="availability">In Stock</div>{buy}')


def added_page() -> str:
    return _doc('<div id="NATC_SMART_WAGON_CONF_MSG_SUCCESS"><h1>Added to cart</h1></div>')


def cart_page(cart: dict[str, int]) -> str:
    rows = []
    for asin, quantity in cart.items():
        p = PRODUCTS[asin]
        binding = f'<span class="sc-product-binding">{p["format"]}</span>' if p.get("format") else ""
        rows.append(f'<div class="a-row sc-list-item" data-asin="{asin}" data-itemtype="active" data-price="{p["price"]}" '
                    f'data-quantity="{quantity}" data-producttitle="{html.escape(p["title"])}">'
                    f'<span class="sc-product-title">{html.escape(p["title"])}</span>{binding}</div>')
    total = sum(float(PRODUCTS[a]["price"]) * q for a, q in cart.items())
    n = sum(cart.values())
    subtotal = (f'<span id="sc-subtotal-label-buybox">Subtotal ({n} item{"s" if n != 1 else ""}):</span>'
                f'<span id="sc-subtotal-amount-buybox">${total:.2f}</span>')
    return _doc(f'<div id="sc-active-cart"><h2 id="sc-active-items-header">Shopping Cart</h2>'
                f'<div data-name="Active Items">{"".join(rows)}</div></div>{subtotal}')


class AmazonShop(FixtureShop):
    def __init__(self):
        super().__init__(popup=False)
        self.amazon_cart: dict[str, int] = {}
        self.hits: dict[str, int] = {}
        # path -> SPECIAL_PAGES names, served one per request in place of the page at that path
        self.interpose: dict[str, list[str]] = {}

    def count(self) -> int:
        return sum(self.amazon_cart.values())

    def hit(self, name: str) -> None:
        self.hits[name] = self.hits.get(name, 0) + 1

    def _render(self, path: str, query: dict) -> tuple[int, bytes, str]:
        if self.interpose.get(path):
            name = self.interpose[path].pop(0)
            back = path + ("?" + urlencode({k: v[0] for k, v in query.items()}) if query else "")
            return 200, _special(name, back).encode(), "text/html"
        if path.startswith("/special/"):
            return 200, _special(path.rsplit("/", 1)[-1], "/").encode(), "text/html"
        if path in ("/errors_page/validateCaptcha", "/errors/validateCaptcha", "/checkpoint/validate"):
            self.hit(path)
            return 302, b"", (query.get("amzn-r") or ["/"])[0]
        if path == "/api/hit":
            self.hit((query.get("name") or ["?"])[0])
            return 200, b"{}", "application/json"
        if path == "/":
            return 200, _doc("<h1>Amazon.com</h1>").encode(), "text/html"
        if path == "/s":
            return 200, search_page().encode(), "text/html"
        for asin, p in PRODUCTS.items():
            if path == p["path"]:
                return 200, product_page(asin).encode(), "text/html"
        if path == "/cart/add-to-cart":
            asin = (query.get("ASIN") or [""])[0]
            self.hit("add-to-cart")
            self.amazon_cart[asin] = self.amazon_cart.get(asin, 0) + 1
            return 302, b"", "/cart/smart-wagon?newItems=1"
        if path == "/cart/smart-wagon":
            return 200, added_page().encode(), "text/html"
        if path == "/gp/cart/view.html":
            return 200, cart_page(self.amazon_cart).encode(), "text/html"
        return 404, b"not found", "text/plain"


    def _handler(self):
        get_only = super()._handler()

        class Handler(get_only):
            def do_POST(self):  # the checkpoint form posts; its return URL is in the query string
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                self.do_GET()

        return Handler


def local_amazon_mapping(base: str, **changes: Any):
    """server/mappings/amazon.json pointed at a local server: its URLs and URL patterns rewritten."""
    raw = json.loads(load_mapping("amazon").path.read_text())
    raw["domain"] = "127.0.0.1"
    port_pattern = r"127\.0\.0\.1:\d+"
    for screen in raw["screens"].values():
        screen["url_pattern"] = screen["url_pattern"].replace(r"amazon\.com", port_pattern)
    for action in raw["actions"].values():
        for step in action["steps"]:
            if "url" in step:
                step["url"] = step["url"].replace("https://www.amazon.com", base)
    raw.update(changes)
    return load_mapping(raw)
