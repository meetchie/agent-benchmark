"""A small local copy of prose.com's accessories flow, served from 127.0.0.1.

It follows the live site as seen on 2026-10-24 (page structure, not content): the accessories
grid is h2 + leaf price per card, product pages have an add-to-cart button, and the cart
page is rendered by script about a second after the page loads, with the line items in
plain divs (no <p>). That late render and those plain divs are the two ways cli/mappings/
prose.json and cli/extractors/prose.js drifted from the March site.

``localize(mapping, base)`` points the real prose mapping at this server, so tests run
the shipped mapping and extractor, not a copy. Nothing leaves 127.0.0.1.
"""

from __future__ import annotations

import html
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from rindler_local import Mapping, load_mapping

# slug -> (card name on /products/accessories, name in the cart, price, size line)
PRODUCTS = {
    "reusable-eye-patches": ("Reusable Eye Patches", "Eye Patches", "$26.00", "1 PAIR, 1.2 OZ"),
    "prose-hair-towel": ("Hair Towel Wrap", "Hair Towel", "$35.00", "23” X 37” IN"),
    "prose-candle": ("Candle", "Arcadia Candle", "$52.00", "8.6 FL OZ"),
    "brushes?variant=brush_boar": ("Boar Bristle Brush", "Boar Bristle", "$85.00", "BRUSH"),
    "brushes?variant=brush_mixed": ("Boar + Nylon Brush", "Boar + Nylon Bristle", "$85.00", "BRUSH"),
    "brushes?variant=brush_detangling": ("Tipped-Metal Brush", "Tipped-Metal Bristle", "$85.00", "BRUSH"),
}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body><a href="#main">Skip to main content</a>
<header><nav>Haircare Skincare Accessories</nav>
<a href="/checkout/accessories" id="cart-link"><span id="cart-count">{count}</span></a></header>
<main>{body}</main><footer><button>About us</button></footer>{script}</body></html>"""

CART_SCRIPT = """<script>
async function render() {
  const cart = await (await fetch('/api/cart')).json();
  const n = cart.length;
  let rows = '';
  let subtotal = 0;
  for (const [index, item] of cart.entries()) {
    subtotal += item.cents;
    rows += '<div class="row"><div class="info"><div>' + item.cart_name + '</div><div>' + item.size + '</div>'
      + '<select aria-label="Please select a quantity"><option>1</option><option>2</option><option>3</option>'
      + '<option>4</option></select></div><div class="actions" style="display:flex;gap:8px"><button onclick="removeItem(' + index + ')">Remove</button>'
      + '<span>' + item.price + '</span></div></div>';
  }
  const money = c => '$' + (c / 100).toFixed(2);
  const summary = cart.map(i => '<div>[1] ' + i.cart_name + '</div><div>' + i.price + '</div>').join('');
  const ship = n ? '$6.95' : 'FREE';
  const total = n ? subtotal + 695 : 0;
  document.querySelector('main').innerHTML =
    '<h1>' + (n ? 'Your cart(' + n + ')' : 'Your cart is empty (0)') + '</h1>' + rows
    + '<h2>Accessorize your routine</h2><button>ADD - $26.00</button>'
    + '<div>ORDER SUMMARY</div>' + summary
    + '<div>Subtotal (' + n + ' item' + (n <= 1 ? '' : 's') + ')</div><div>' + money(subtotal) + '</div>'
    + '<div>Shipping</div><div>' + ship + '</div><div>Today’s total (pre-tax)</div><div>' + money(total) + '</div>'
    + '<button>CHECKOUT</button>';
}
setTimeout(render, 1200);  // the real cart page fills in about a second after it loads
async function removeItem(index) { await fetch('/api/remove?index=' + index); render(); }
</script>"""


class ProseShop:
    def __init__(self):
        self.cart: list[dict] = []
        self.requests: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    # -- pages ---------------------------------------------------------------------

    def page(self, title: str, body: str, script: str = "") -> bytes:
        return PAGE.format(title=html.escape(title), body=body, script=script, count=len(self.cart)).encode()

    def route(self, path: str, query: str) -> tuple[int, str, bytes]:
        if path == "/":
            return 200, "text/html", self.page("Prose", "<h1>Skin science, made deeply personal</h1><p>Meet our most advanced custom skincare yet.</p>")
        if path == "/products/accessories":
            cards = "".join(
                f'<a href="/products/{slug}"><div><h2>{html.escape(card)}</h2><div><span>{price}</span></div></div></a>'
                for slug, (card, _cart, price, _size) in PRODUCTS.items()
            )
            cards += '<a href="/gift"><div><h2>Digital Gift Cards</h2><div><span>From $50.00</span></div></div></a>'
            # As on the live site, the page heading and the closing h2 are in the first HTML and the
            # product grid is put in by script a moment later.
            body = '<h1>Accessories</h1><div id="grid"></div><h2>Self-care meets sustainability</h2>'
            script = f"<script>setTimeout(function () {{ document.getElementById('grid').innerHTML = {json.dumps(cards)}; }}, 700);</script>"
            return 200, "text/html", self.page("Accessories", body, script)
        slug = path.removeprefix("/products/") + (f"?{query}" if query else "")
        if path.startswith("/products/") and slug in PRODUCTS:
            card, _cart, price, _size = PRODUCTS[slug]
            button = f'<button data-testid="add-to-cart" onclick="fetch(\'/api/add?slug={slug}\').then(() => {{ document.getElementById(\'cart-count\').textContent = \'+\'; }})">ADD TO CART</button>'
            if slug == "reusable-eye-patches":
                button += button  # the live eye patches page has two add-to-cart buttons (main and sticky bar)
            body = f"<h1>{html.escape(card)}</h1><p>Handcrafted. A longer description of {html.escape(card)}.</p><span>{price}</span>{button}"
            return 200, "text/html", self.page(card, body)
        if path == "/checkout/accessories":
            return 200, "text/html", self.page("Cart", "<div>Loading your cart</div>", CART_SCRIPT)
        if path == "/gift":
            body = "<h1>Digital gift card</h1><div>Choose your gift amount</div><button>$50</button><button>CHECKOUT</button>"
            return 200, "text/html", self.page("Gift", body)
        if path == "/api/cart":
            return 200, "application/json", json.dumps(self.cart).encode()
        if path == "/api/add":
            slug = parse_qs(query).get("slug", [""])[0]
            if slug in PRODUCTS:
                card, cart_name, price, size = PRODUCTS[slug]
                cents = int(re.sub(r"\D", "", price))
                self.cart.append({"slug": slug, "cart_name": cart_name, "price": price, "size": size, "cents": cents})
            return 200, "application/json", b"{}"
        if path == "/api/remove":
            index = int(parse_qs(query).get("index", ["0"])[0])
            if 0 <= index < len(self.cart):
                self.cart.pop(index)
            return 200, "application/json", b"{}"
        return 404, "text/plain", b"not found"

    def _handler(self):
        shop = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = urlsplit(self.path)
                shop.requests.append(self.path)
                status, kind, body = shop.route(parts.path, parts.query)
                self.send_response(status)
                self.send_header("Content-Type", f"{kind}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        return Handler


def localize(mapping: Mapping, base: str) -> Mapping:
    """The prose mapping pointed at ``base`` (a http://127.0.0.1:PORT address)."""
    host = base.split("//", 1)[1]
    pattern_host = re.escape(host)

    def walk(value):
        if isinstance(value, str):
            value = value.replace("https://www.prose.com", base).replace("prose\\.com", pattern_host)
            return "127.0.0.1" if value == "www.prose.com" else value
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) if k != "page_extractor" else v for k, v in value.items()}
        return value

    return load_mapping(walk(mapping.raw))
