"""A tiny local shop for the rindler_local tests: static-looking HTML from an in-process server.

Pages: / (landing), /search?q=..., /products/<slug>, /cart, /checkout. Every page shows a small
newsletter popup a moment after it loads (closing it calls /api/dismiss, which the tests count).
Cart state lives on the server object, so add/remove are visible across page loads. Nothing leaves
127.0.0.1.
"""

from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MAPPING_PATH = Path(__file__).parent / "fixtures" / "fixture_shop.json"

PRODUCTS = [
    {"slug": "iron-chain-belt", "name": "Iron Chain Belt", "price": "$29.00", "was": "$40.00"},
    {"slug": "leather-belt", "name": "Plain Leather Belt", "price": "$45.00", "was": "$60.00"},
    {"slug": "spike-wallet-chain", "name": "Spike Wallet Chain", "price": "$24.00", "was": "$39.00"},
]


def _page(title: str, body: str, *, popup: bool = True) -> bytes:
    popup_html = ""
    if popup:
        popup_html = """
<div id="newsletter" role="dialog" style="display:none;position:fixed;top:0;right:0;width:120px;background:#fff;z-index:10">
  <p>Join our list</p><button aria-label="Close dialog" onclick="fetch('/api/dismiss'); document.getElementById('newsletter').remove()">x</button>
</div>
<script>setTimeout(function(){var d=document.getElementById('newsletter'); if(d) d.style.display='block';}, 300);</script>"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body><header><a id="cart-link" href="/cart">Cart <span id="cart-count">{{count}}</span></a></header>
<main>{body}</main>{popup_html}</body></html>""".encode()


class FixtureShop:
    def __init__(self, popup: bool = True):
        self.popup = popup
        self.cart: dict[str, int] = {}
        self.requests: list[str] = []
        self.dismissals = 0
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

    def count(self) -> int:
        return sum(self.cart.values())

    def _render(self, path: str, query: dict) -> tuple[int, bytes, str]:
        shop = self
        if path == "/":
            body = """<h1>Fixture Shop</h1>
<form action="/search"><input name="q" placeholder="Search the shop"><button type="submit">Go</button></form>
<label for="sort">Sort</label><select id="sort" onchange="document.title='sorted:'+this.value">
<option value="relevance">Relevance</option><option value="price">Price, low to high</option></select>"""
            return 200, _page("Fixture Shop", body, popup=shop.popup), "text/html"
        if path == "/search":
            q = (query.get("q") or [""])[0].lower()
            words = [w for w in q.split() if w]
            hits = [p for p in PRODUCTS if all(w in p["name"].lower() for w in words)] if words else PRODUCTS
            cards = "".join(
                f"""<li><h3><a id="CardLink--{i}" href="/products/{p['slug']}">{html.escape(p['name'])} 25%</a></h3>
<span>Regular price {p['price']} Sale price {p['was']}</span></li>"""
                for i, p in enumerate(hits)
            )
            return 200, _page("Search", f"<h1>Search results</h1><ul>{cards}</ul>", popup=shop.popup), "text/html"
        if path.startswith("/products/"):
            slug = path.rsplit("/", 1)[-1]
            product = next((p for p in PRODUCTS if p["slug"] == slug), None)
            if product is None:
                return 404, b"not found", "text/plain"
            body = f"""<h1>{html.escape(product['name'])}</h1><p>{product['price']}</p>
<button class="atc-button" onclick="fetch('/api/add?slug={slug}').then(function(){{document.getElementById('added').hidden=false; document.getElementById('cart-count').textContent=String(Number(document.getElementById('cart-count').textContent)+1);}})">Add to cart</button>
<div id="added" hidden>Added to cart</div>"""
            return 200, _page(product["name"], body, popup=shop.popup), "text/html"
        if path == "/cart":
            rows = "".join(
                f"""<li><span>{html.escape(p['name'])}</span> <span>{p['price']}</span> <span>Qty: {shop.cart[p['slug']]}</span>
<a aria-label="Remove {html.escape(p['name'])}" href="/api/remove?slug={p['slug']}">Remove</a></li>"""
                for p in PRODUCTS if shop.cart.get(p["slug"])
            )
            body = f"<h1>Your cart</h1><ul>{rows}</ul><a id='checkout' href='/checkout'>Check out</a>"
            return 200, _page("Cart", body, popup=shop.popup), "text/html"
        if path == "/checkout":
            body = """<h1>Checkout</h1><input name="code" placeholder="Discount code">
<button aria-label="Apply Discount Code" onclick="document.getElementById('msg').textContent = document.querySelector('input[name=code]').value === 'SPRING' ? 'Order discount applied' : 'Invalid code'">Apply</button>
<p id="msg"></p>"""
            return 200, _page("Checkout", body, popup=shop.popup), "text/html"
        if path == "/api/add":
            slug = (query.get("slug") or [""])[0]
            shop.cart[slug] = shop.cart.get(slug, 0) + 1
            return 200, json.dumps({"count": shop.count()}).encode(), "application/json"
        if path == "/api/dismiss":
            shop.dismissals += 1
            return 200, b"{}", "application/json"
        if path == "/api/remove":
            slug = (query.get("slug") or [""])[0]
            shop.cart.pop(slug, None)
            return 302, b"", "/cart"
        return 404, b"not found", "text/plain"

    def _handler(self):
        shop = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                shop.requests.append(self.path)
                status, body, ctype = shop._render(parts.path, parse_qs(parts.query))
                if status == 302:
                    self.send_response(302)
                    self.send_header("Location", ctype)
                    self.end_headers()
                    return
                body = body.replace(b"{count}", str(shop.count()).encode())
                self.send_response(status)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
