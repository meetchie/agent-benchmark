"""
task_generator.py — Generates benchmark tasks for browser automation agents.

Functions:
  extract_metadata(html, url) -> dict
  validate_url(url) -> bool           (blocking DNS lookup)
  check_url(url) -> None              (async; raises ValueError saying why a URL is refused)
  generate_tasks(metadata) -> list[dict]
  fetch_and_generate(url) -> list[dict]
"""

import asyncio
import re
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import ssl
import certifi
import aiohttp
from bs4 import BeautifulSoup

import llm

logger = logging.getLogger(__name__)

# What the model must answer with: 3 tasks, or an error for a non-commerce site.
# With Anthropic this is enforced through structured outputs; both keys are optional
# so a refusal-by-JSON ({"error": "..."}) stays valid.
TASKS_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "goal": {"type": "string"},
                },
                "required": ["label", "goal"],
            },
        },
        "error": {"type": "string"},
    },
}

# Three tasks are about 1.5K output tokens; this is generous headroom.
_TASKGEN_MAX_TOKENS = 8000

PROMPT_TEMPLATE = """You generate benchmark tasks that stress-test AI browser agents on real commerce websites. The goal is to expose the specific UI interactions where agents fail — NOT to test whether the agent is smart, but whether it can actually navigate the website's interface correctly.

AGENT FAILURE PATTERNS (design tasks that trigger these):
1. PRODUCT DISAMBIGUATION: Agents blindly click the first search result (often a sponsored ad) instead of scrolling to find the correct product. They confuse similar product names, miss size/pack-count differences, and pick the wrong variant from search results.
2. QUANTITY MANIPULATION: Agents can't use quantity dropdowns or +/- buttons, or they leave quantity at 1 when told to add more.
3. VARIANT SELECTION ON PRODUCT PAGE: Once on a product page, agents fail to select the right size, color, or style from dropdown menus, swatch selectors, or option tiles. They especially struggle when selecting one option changes available choices for another (e.g., selecting a color changes available sizes).
4. MULTI-ITEM CART BUILDING: Agents add one item then get stuck. They click "Proceed to Checkout" instead of "Continue Shopping", or they can't navigate back to search for a second item. They lose context when returning to browse.
5. FILTER & SORT: Agents struggle to use sidebar filters (brand, price range, ratings) or sort dropdowns to narrow results before selecting a product.
6. MODAL/POPUP HANDLING: Agents get stuck on cookie banners, "Add warranty?" prompts, "Subscribe & Save" overlays, "Choose your delivery location" popups, or newsletter signup modals.
7. SCROLL & PAGINATION: Agents only look at the first few search results and miss the right product further down. They fail to scroll or go to page 2.
8. CONDITIONAL UI: Agents miss buttons or options that only appear after a prior selection (e.g., "Add to Cart" greyed out until size is selected).

TASK DESIGN RULES:
- Each task MUST trigger at least 2-3 of the failure patterns above
- Use GENERIC product categories that definitely exist on the site. Search for categories like "running shoes", "wireless headphones", "yoga mat", "backpack" — things every major retailer sells. Then specify the variant (size, color, brand) the agent should pick from the results.
- NEVER reference a specific brand+model that you aren't certain the site sells. Instead, describe what the agent should look for: "Find a yoga mat that is at least 6mm thick, in a purple or blue color" rather than "Find the Gaiam Essentials 1/2 inch mat in purple".
- Create variant selection challenges: the agent must pick a specific size, color, or option from the product page, not just click "Add to Cart" on the first thing it finds.
- Require specific QUANTITIES > 1 to test quantity manipulation
- Require MULTIPLE items from different categories in one session
- Include detailed VERIFICATION: agent must go to cart and confirm items, quantities, and variants
- Do NOT require login, payment, or setting a delivery address on sites like Amazon, Target, Walmart, Best Buy, Nike, or Costco (these don't require an address to add items to cart)
- Only use "Set delivery address to 1 Times Square, New York, NY 10036" for sites that REQUIRE a location to browse products: Instacart, Shipt, DoorDash, Domino's, Chipotle
- Keep labels under 60 characters
- Write naturally, like instructions a human would give. Use positive phrasing: "Find the 6-pack (not the 12-pack)" rather than "DO NOT select the 12-pack". Never use "CRITICAL", "TRAP", "must NOT", "DO NOT pick/choose/select". When disambiguating, use parenthetical clarification.
- Only reference features the site actually has. Retail sites (Amazon, Target, Walmart, Best Buy, Nike, Costco) sell packaged products — no custom food, no made-to-order items, no food customization. Restaurant sites (Domino's, Chipotle, DoorDash) do have food customization.
- Steps should be specific enough that success/failure is unambiguous

GENERATE 3 TASKS AT ESCALATING DIFFICULTY:

TASK 1 — SINGLE ITEM, SPECIFIC VARIANT (5-7 steps):
Search for a product category. From the results, find a product with specific attributes (not the first result — the agent must scroll or filter). On the product page, select a specific variant (size/color/style). Set quantity > 1. Add to cart. Go to cart and verify the correct item, variant, and quantity.

TASK 2 — TWO ITEMS, DIFFERENT CATEGORIES (8-10 steps):
Search for a product. Navigate results, pick the right one, select a variant (size/color). Set quantity > 1. Add to cart. Go BACK to shopping (not checkout). Search for a completely different product in another category. Select its variant. Add to cart. Go to cart. Verify both items are present with correct variants and quantities.

TASK 3 — COMPLEX MULTI-STEP WITH FILTERS (10-13 steps):
Search for a product category. Use a filter or sort option to narrow results (e.g., filter by brand, price range, or rating). Find the right product among filtered results. Select multiple variant options (e.g., size AND color). Set quantity > 1. Add to cart. Return to shopping. Search for a second product in a different category. Use a different filter. Select its variant. Add to cart. Go to cart. Verify both items with all variant details and quantities correct.

EXAMPLES:

Example 1 (Amazon — TASK 1):
  label: "Add 3 specific dry erase markers to cart"
  goal: |
    Search for "dry erase markers".
    Scroll through the results to find a chisel tip marker set (not fine tip or ultra-fine). Look for a 4-pack with assorted colors (not a single-color pack, not an 8-pack or 12-pack).
    Click on the correct product.
    On the product page, if there are style or size options, make sure "Chisel Tip" and "4-pack" are selected.
    Set quantity to 3.
    Click "Add to Cart". If a "Subscribe & Save" or warranty prompt appears, dismiss it and choose one-time purchase.
    Go to cart. Confirm it shows chisel tip markers, 4-pack assorted colors, quantity 3.

Example 2 (Domino's — TASK 2):
  label: "Order a custom pizza and cinnamon twists"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036. Wait for autocomplete dropdown, select the first suggestion, and confirm.
    Go to Menu.
    Select "Build Your Own" pizza.
    Choose: Medium size, Hand Tossed crust (not Pan, Thin, or Brooklyn style).
    Add exactly 3 toppings: Pepperoni, Green Peppers, and Black Olives. No other toppings.
    Click "Add to Order".
    Navigate back to the menu (do not go to checkout).
    Find the "Sides" or "Bread" section.
    Add "Cinnamon Bread Twists" (not regular Bread Twists or Parmesan).
    Go to cart/order summary. Confirm: 1 Medium Hand Tossed pizza with exactly Pepperoni + Green Peppers + Black Olives, and 1 Cinnamon Bread Twists. Should be exactly 2 items.

Example 3 (Amazon — TASK 3):
  label: "Build a filtered cart with headphones and a backpack"
  goal: |
    Search for "wireless headphones".
    Use the sidebar filters to select "4 Stars & Up" under Customer Reviews.
    From the filtered results, find an over-ear (not in-ear or on-ear) Bluetooth headphone. Click on it.
    On the product page, select the black color option if available.
    Set quantity to 1.
    Click "Add to Cart". Dismiss any warranty or accessory prompts.
    Click "Continue Shopping" or navigate back to the Amazon homepage.
    Search for "laptop backpack".
    Sort results by "Price: Low to High".
    Find a backpack that fits at least a 15-inch laptop (check the title or description for laptop size). Click on it.
    On the product page, select a gray or black color if available. Set quantity to 2.
    Add to cart.
    Go to cart. Verify: (1) over-ear wireless headphones in black, quantity 1, and (2) laptop backpack in gray or black, quantity 2.

IMPORTANT: This benchmark is ONLY for commerce/transactional websites. If the website is NOT a commerce site, respond with:
{{"error": "This website is not a commerce or transactional site. The benchmark is designed for e-commerce, food delivery, grocery, and similar shopping/ordering websites."}}

If the website IS a commerce site, respond with a JSON object with a "tasks" key containing an array of 3 objects, each with "label" (string) and "goal" (string) fields. No markdown, no explanation.

WEBSITE INFORMATION:
Title: {title}
Description: {description}
Content preview: {visible_text}
URL: {url}"""


def extract_metadata(html: str, url: str) -> dict:
    """Extract title, meta description, and visible text from raw HTML.

    Returns a dict with keys: title, description, visible_text, url.
    Strips script/style/noscript tags. Limits visible_text to 1000 chars.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Extract meta description
    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()

    # Remove non-visible tags before extracting text
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    visible_text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    visible_text = re.sub(r"\s+", " ", visible_text).strip()
    visible_text = visible_text[:1000]

    return {
        "title": title,
        "description": description,
        "visible_text": visible_text,
        "url": url,
    }


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _url_host(url: str) -> str | None:
    """The host of an http(s) URL that is worth resolving, or None if the URL is not allowed.

    Rejects other schemes, a missing host, and the host names that are internal by name.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    hostname = parsed.hostname
    if not hostname:
        return None
    # Block obviously dangerous hostnames
    if hostname in ("localhost", "metadata.google.internal"):
        return None
    return hostname


def _resolves_to_public_addresses(addrinfo) -> bool:
    """False if any resolved address is private, loopback, link-local or otherwise internal."""
    for info in addrinfo:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if any(ip in network for network in _PRIVATE_NETWORKS):
            return False
    return True


def validate_url(url: str) -> bool:
    """Validate URL scheme and block private/internal IPs (including via DNS resolution).

    Blocking: the DNS lookup runs on the calling thread. Async code uses ``check_url``.
    """
    hostname = _url_host(url)
    if hostname is None:
        return False
    # Resolve hostname to IPs and check all of them
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return False  # Can't resolve — reject
    return _resolves_to_public_addresses(addrinfo)


async def check_url(url: str) -> None:
    """Raise ValueError unless ``url`` is an http(s) URL on a public host.

    The same rules as ``validate_url``, with the DNS lookup off the event loop and a
    message that says why: "Could not resolve this host: ..." when the host name has no
    address (a typo or a dead domain), "Invalid or disallowed URL: ..." for everything
    the SSRF guard blocks.
    """
    hostname = _url_host(url)
    if hostname is None:
        raise ValueError(f"Invalid or disallowed URL: {url}")
    try:
        addrinfo = await asyncio.get_running_loop().getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        raise ValueError(f"Could not resolve this host: {hostname}") from None
    if not _resolves_to_public_addresses(addrinfo):
        raise ValueError(f"Invalid or disallowed URL: {url}")


# Domains that are obviously not commerce sites
_NON_COMMERCE_DOMAINS = {
    "google.com", "gmail.com", "youtube.com", "facebook.com", "twitter.com",
    "x.com", "instagram.com", "linkedin.com", "reddit.com", "wikipedia.org",
    "github.com", "stackoverflow.com", "calendar.google.com", "docs.google.com",
    "drive.google.com", "notion.so", "slack.com", "discord.com", "twitch.tv",
    "netflix.com", "spotify.com", "tiktok.com", "pinterest.com", "medium.com",
}

# Known commerce/transactional domains (SPAs that return thin HTML shells)
_KNOWN_COMMERCE_DOMAINS = {
    # Grocery & delivery
    "shipt.com", "instacart.com", "kroger.com", "safeway.com", "wholefoods.com",
    "albertsons.com", "freshdirect.com", "thrivemarket.com", "hungryroot.com",
    "misfitsmarket.com", "sayweee.com", "imperfectfoods.com", "peapod.com",
    "heb.com", "publix.com", "wegmans.com", "sprouts.com", "traderjoes.com",
    "foodlion.com", "harristeeter.com", "vons.com", "acmemarkets.com",
    "shaws.com",
    # Food delivery aggregators
    "doordash.com", "grubhub.com", "ubereats.com", "seamless.com",
    "postmates.com", "caviar.com", "gopuff.com", "favor.com", "ezcater.com",
    "slice.co", "chownow.com",
    # Restaurant ordering (QSR / fast casual)
    "dominos.com", "chipotle.com", "mcdonalds.com", "starbucks.com",
    "papajohns.com", "pizzahut.com", "tacobell.com", "wendys.com", "bk.com",
    "chickfila.com", "panerabread.com", "sweetgreen.com", "shakeshack.com",
    "popeyes.com", "fiveguys.com", "dunkindonuts.com", "subway.com",
    "wingstop.com", "jimmyjohns.com", "qdoba.com", "whataburger.com",
    "jackinthebox.com", "sonic.com",
    # Big retail / general merchandise
    "amazon.com", "walmart.com", "target.com", "costco.com", "bestbuy.com",
    "samsclub.com", "kohls.com", "jcpenney.com", "macys.com", "nordstrom.com",
    "bloomingdales.com", "tjmaxx.com",
    # Fashion & apparel
    "nike.com", "adidas.com", "zappos.com", "shein.com", "zara.com", "hm.com",
    "asos.com", "nordstromrack.com", "gap.com", "oldnavy.com", "uniqlo.com",
    "lululemon.com", "underarmour.com", "puma.com", "newbalance.com",
    "urbanoutfitters.com", "anthropologie.com", "abercrombie.com", "ae.com",
    "jcrew.com", "allbirds.com", "everlane.com", "revolve.com", "ssense.com",
    "farfetch.com", "fashionnova.com", "forever21.com",
    # Electronics & tech
    "newegg.com", "bhphotovideo.com", "microcenter.com", "apple.com",
    "samsung.com", "dell.com", "adorama.com",
    # Home, furniture & improvement
    "wayfair.com", "homedepot.com", "lowes.com", "ikea.com",
    "crateandbarrel.com", "westelm.com", "potterybarn.com", "cb2.com",
    "overstock.com", "williams-sonoma.com", "acehardware.com", "menards.com",
    "article.com",
    # Pharmacy & health
    "cvs.com", "walgreens.com", "riteaid.com", "capsule.com",
    # Quick commerce / convenience
    "getir.com",
    # Alcohol delivery
    "drizly.com", "totalwine.com", "wine.com", "vivino.com",
    # Pet supplies
    "chewy.com", "petco.com", "petsmart.com",
    # Beauty & personal care
    "sephora.com", "ulta.com", "glossier.com", "bathandbodyworks.com",
    "dermstore.com",
    # Auto parts
    "autozone.com", "oreillyauto.com", "advanceautoparts.com", "rockauto.com",
    # Resale marketplaces
    "ebay.com", "etsy.com", "mercari.com", "poshmark.com", "depop.com",
    "stockx.com", "goat.com", "therealreal.com", "thredup.com", "grailed.com",
    "offerup.com", "vinted.com",
    # International commerce
    "flipkart.com", "shopee.com", "lazada.com", "coupang.com",
    "mercadolibre.com", "zalando.com", "aliexpress.com", "rakuten.com",
    "temu.com",
    # Specialty / niche
    "iherb.com", "dickssportinggoods.com", "rei.com", "cabelas.com",
    "basspro.com", "gamestop.com", "barnesandnoble.com", "wish.com",
    "fivebelow.com", "dollartree.com",
    # Tickets & travel (transactional SPAs)
    "ticketmaster.com", "stubhub.com", "seatgeek.com", "eventbrite.com",
    "airbnb.com", "booking.com", "expedia.com", "kayak.com", "priceline.com",
}


def _get_domain(url: str) -> str:
    """Extract the base domain from a URL (strips www. prefix)."""
    hostname = urlparse(url).hostname or ""
    return hostname.replace("www.", "").lower()


def _check_commerce_site(metadata: dict) -> None:
    """Raise ValueError if the site doesn't look like a commerce site."""
    domain = _get_domain(metadata.get("url", ""))

    # Block known non-commerce domains
    if domain in _NON_COMMERCE_DOMAINS:
        raise ValueError(
            "This website is not a commerce site. The benchmark is designed for "
            "e-commerce, food delivery, grocery, and similar shopping/ordering websites."
        )

    # For everything else, let the model decide if it's commerce or not


def generate_tasks(metadata: dict) -> list[dict]:
    """Ask the task-generation model for 3 benchmark tasks for a website.

    Returns list of dicts with keys: id, label, goal.
    Raises ValueError if the site is not a commerce site, or the model declines
    to write tasks for it. Other model failures (API error, truncated or
    unparseable reply) raise ``llm.LLMError``.
    """
    _check_commerce_site(metadata)

    # Sanitize metadata to prevent prompt injection
    safe_url = metadata.get("url", "")[:500].replace("\n", "").replace("\r", "")
    safe_title = metadata.get("title", "")[:200].replace("\n", " ")
    safe_desc = metadata.get("description", "")[:500].replace("\n", " ")
    safe_text = metadata.get("visible_text", "")[:1000].replace("\n", " ")

    prompt = PROMPT_TEMPLATE.format(
        title=safe_title,
        description=safe_desc,
        visible_text=safe_text,
        url=safe_url,
    )

    # If domain is known commerce, tell the model so it doesn't reject thin SPA shells
    domain = _get_domain(metadata.get("url", ""))
    if domain in _KNOWN_COMMERCE_DOMAINS:
        prompt += (
            "\n\nNOTE: This is a confirmed commerce/transactional website. "
            "Even if the HTML content appears sparse (common with single-page apps), "
            "generate tasks based on what you know about this site."
        )

    try:
        data = llm.complete_json(
            None, prompt, TASKS_SCHEMA, role="taskgen", max_tokens=_TASKGEN_MAX_TOKENS
        )
    except llm.LLMError as e:
        if e.kind == "refusal":
            logger.warning("task generation declined: %s", e)
            raise ValueError(
                "The model declined to write benchmark tasks for this website. Try a different URL."
            ) from e
        raise

    cost = getattr(data, "cost_usd", None)
    logger.info(
        "task generation: model=%s cost=%s",
        getattr(data, "model", "?"), "n/a" if cost is None else f"${cost:.4f}",
    )

    # The model may reject non-commerce sites
    if data.get("error"):
        logger.info("task generation: the model rejected %s: %s", safe_url, str(data["error"])[:200])
        raise ValueError(str(data["error"]))

    tasks_raw = data.get("tasks") or []
    if not isinstance(tasks_raw, list) or not tasks_raw:
        logger.warning("task generation: the model returned no tasks for %s: %s", safe_url, str(dict(data))[:200])
        raise ValueError("Could not generate benchmark tasks for this website. Try a different URL.")

    # Truncate to 3 tasks and add sequential IDs
    tasks = []
    for i, task in enumerate(tasks_raw[:3]):
        tasks.append({
            "id": i + 1,
            "label": task.get("label", ""),
            "goal": task.get("goal", ""),
        })

    return tasks


async def fetch_and_generate(url: str) -> list[dict]:
    """Fetch a URL, extract metadata, and generate benchmark tasks.

    For known commerce domains, skips the HTTP fetch (they block server-side
    requests from data center IPs) and generates tasks from domain knowledge alone.

    For unknown domains, fetches HTML via aiohttp with 15s timeout, checks
    Content-Type is text/html, extracts metadata, and calls generate_tasks.

    Raises:
        ValueError: for an invalid or disallowed URL, a host name that does not resolve,
            or non-HTML content type.
        ConnectionError: for fetch failures (network errors, bad status codes).
    """
    await check_url(url)

    domain = _get_domain(url)

    # Known commerce sites block server-side fetches from data center IPs.
    # Skip the HTML fetch and generate tasks from the model's domain knowledge.
    # The model call is blocking, so it runs in a thread and the event loop (status
    # polls, other runs, the client-disconnect check) stays responsive.
    if domain in _KNOWN_COMMERCE_DOMAINS:
        metadata = {"title": "", "description": "", "visible_text": "", "url": url}
        return await asyncio.to_thread(generate_tasks, metadata)

    timeout = aiohttp.ClientTimeout(total=15)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status == 403:
                    raise ConnectionError(
                        "This site is blocking automated access. Try a different website."
                    )
                if response.status >= 400:
                    raise ConnectionError(
                        f"Could not reach this site (HTTP {response.status}). Try a different URL."
                    )

                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    raise ValueError(
                        f"URL did not return HTML content. Content-Type: {content_type}"
                    )

                html = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ConnectionError("This site took too long to respond or is unreachable. Try a different URL.") from exc

    metadata = extract_metadata(html, url)
    return await asyncio.to_thread(generate_tasks, metadata)
