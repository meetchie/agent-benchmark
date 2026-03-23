"""
task_generator.py — Generates benchmark tasks for browser automation agents.

Functions:
  extract_metadata(html, url) -> dict
  validate_url(url) -> bool
  generate_tasks(metadata) -> list[dict]
  fetch_and_generate(url) -> list[dict]
"""

import json
import re
import ipaddress
import socket
from urllib.parse import urlparse

import ssl
import certifi
import aiohttp
from bs4 import BeautifulSoup
from openai import OpenAI

PROMPT_TEMPLATE = """You generate benchmark tasks that stress-test AI browser agents on real commerce websites. The goal is to expose the specific UI interactions where agents fail — NOT to test whether the agent is smart, but whether it can actually navigate the website's interface correctly.

AGENT FAILURE PATTERNS (design tasks that trigger these):
1. PRODUCT DISAMBIGUATION: Agents blindly click the first search result instead of finding the correct variant. They confuse "organic" with "regular", "bagged" with "loose", "2%" with "whole", "diet" with "regular".
2. QUANTITY MANIPULATION: Agents can't use quantity +/- buttons, can't type into small quantity fields, or set wrong amounts. They often leave quantity at 1 when told to add more.
3. VARIANT SELECTION: Agents fail on size/color pickers — especially color swatches (not dropdowns), size matrices, and options that only appear after selecting another option (e.g., color must be selected before size shows).
4. MULTI-ITEM CART BUILDING: Agents add one item successfully but fail to navigate BACK to continue shopping. They get stuck on cart/checkout pages or lose context when returning to browse.
5. CUSTOMIZATION FLOWS: Agents fail on pizza topping selectors, burger modification checkboxes, product personalization fields. They skip required customizations or add wrong ones.
6. ADDRESS/LOCATION FORMS: Agents can't properly interact with address autocomplete (type, wait for dropdown, click suggestion), or they skip the location step entirely and get blocked.
7. MODAL/POPUP HANDLING: Agents get stuck on cookie banners, newsletter popups, age verification gates, or "choose your store" modals that block the page.
8. PAGINATION & SCROLL: Agents fail to scroll down to see more products, miss "Load More" buttons, or can't navigate beyond the first page of results.
9. CONDITIONAL UI ELEMENTS: Agents miss elements that only appear after a prior action (e.g., "Add to Cart" button only visible after selecting a size, delivery time slots only shown after entering address).
10. FILTER & SORT CONTROLS: Agents struggle with sidebar filters, multi-select checkboxes, price range sliders, and sort dropdowns that require precise interaction sequences.

TASK DESIGN RULES:
- Each task MUST trigger at least 2-3 of the failure patterns above
- Pick SPECIFIC products the site actually sells — name exact items with exact attributes (sizes, colors, flavors, pack counts)
- Create situations where the agent must find a particular variant among similar options. Specify what IS wanted with precise attributes (e.g., "Select the chisel tip markers in the 4-pack with assorted colors" rather than "must NOT pick the fine tip")
- Require specific QUANTITIES > 1 to test quantity manipulation
- Require MULTIPLE items added in one session to test cart building flow
- Include detailed VERIFICATION: agent must go to cart and confirm exact items, quantities, variants, and customizations
- Use address "1 Times Square, New York, NY 10036" when needed
- Do NOT require login or payment
- Keep labels under 60 characters
- The label and goal text should read naturally, like instructions a human would give. NEVER use negative phrasing like "CRITICAL", "TRAP", "must NOT", "DO NOT pick", "DO NOT choose", "DO NOT select", "avoid", or "do not". Instead, ALWAYS specify what IS wanted clearly: "Select the 1/2 inch thick mat in purple" rather than "must NOT select the 1/4 inch, must NOT select black". When you need to disambiguate, use parenthetical clarification: "Find the 48-pack (not the 72-pack)" rather than "Do not choose the 72-pack". Use positive phrasing to specify the correct choice.
- Do NOT use words like "trap", "trick", or "gotcha" in labels or goals
- Only reference products and customizations that actually exist on the site. STRICT RULE: The following sites sell PACKAGED PRODUCTS ONLY and do NOT offer any food customization (no custom pizza, no custom cake, no build-your-own sandwich, no made-to-order food): Walmart, Costco, Instacart, Shipt, Amazon, Target, Best Buy, Nike. For these sites, "customization" means variant selection (size, color, quantity, flavor of a packaged item) — not building custom food. Only generate custom food tasks (pizza toppings, burrito fillings, etc.) for actual restaurant ordering sites like Domino's, Chipotle, or DoorDash. Never invent product categories or customization features the site does not have.
- Steps should be specific enough that success/failure is unambiguous, but written in plain instructional language

GENERATE 3 TASKS AT THESE LEVELS:

LEVEL 1 — PRODUCT + VARIANT (5-7 steps):
Search for a specific product. Navigate through results to find the CORRECT variant (not just first result). Select specific size/color/option. Set quantity > 1. Add to cart. Verify correct item with correct options in cart.

LEVEL 2 — CUSTOMIZATION + SECOND ITEM (7-9 steps):
Set delivery address (with autocomplete interaction). Find a product that requires customization or variant selection. Complete customization with specific choices. Add to cart. Navigate BACK to shopping. Find and add a completely different product. Verify BOTH items in cart with correct details.

LEVEL 3 — FULL WORKFLOW (9-12 steps):
Set delivery address. Navigate to a specific section. Add a product with a specific variant — the agent must look past similar options to find the right one (e.g., "the 1lb bag" among 1lb, 2lb, and 5lb options). Set quantity to a specific number > 1. Add to cart. Go back and search for a second product in a different category. This product requires selecting from a set of options (size, color, flavor, etc.). Add to cart. Go to cart. Verify: correct 2 products, correct quantities, correct variants/options, correct customizations. Report the subtotal.

EXAMPLES:

Example 1 (Amazon — LEVEL 1):
  label: "Add 3 chisel-tip Expo marker packs to cart"
  goal: |
    Search for "Expo dry erase markers".
    From the results, find the "EXPO Low-Odor Dry Erase Markers, Chisel Tip" in the 4-pack with assorted colors (not single color packs, not the 8-pack or 12-pack, and not fine tip or ultra-fine).
    Click on the correct product.
    On the product page, set quantity to 3.
    Click "Add to Cart".
    VERIFY: Go to cart. Confirm it shows EXPO markers, Chisel Tip, 4-pack assorted colors, quantity 3.

Example 2 (Domino's — LEVEL 2):
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
    VERIFY: Go to cart/order summary. Confirm: 1 Medium Hand Tossed pizza with exactly Pepperoni + Green Peppers + Black Olives, and 1 Cinnamon Bread Twists. Should be exactly 2 items.

Example 3 (Instacart — LEVEL 3):
  label: "Build a 3-item grocery cart from one store"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036. Wait for autocomplete and select the first suggestion.
    When stores load, select the first major grocery store available.
    Search for "Granny Smith Apples".
    Find loose individual Granny Smith apples (not a pre-bagged item like "3lb bag" or "5ct bag"). Select the individual/per-lb option.
    Set quantity to 6 individual apples (or approximately 3 lbs if sold by weight).
    Add to cart.
    Search for "Milk".
    Find a gallon of whole milk. It should say "Whole" (not 2%, Skim, Fat-Free, or Organic unless that's the only whole milk option).
    Add 1 gallon to cart.
    Search for "Advil".
    Find Advil (Ibuprofen) in tablet or caplet form (not Liqui-Gels or Advil PM). Select the smallest pack size available (e.g., 24ct or 50ct, not 100ct+).
    Add to cart.
    VERIFY: Go to cart. Confirm exactly 3 distinct products: (1) Granny Smith Apples, qty 6 or ~3lbs, (2) Whole Milk, 1 gallon, (3) Advil tablets/caplets, smallest size. All from the same store.

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


def validate_url(url: str) -> bool:
    """Validate URL scheme and block private/internal IPs (including via DNS resolution)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block obviously dangerous hostnames
    if hostname in ("localhost", "metadata.google.internal"):
        return False

    # Resolve hostname to IPs and check all of them
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False  # Can't resolve — reject

    private_networks = [
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

    for info in addrinfo:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
            for network in private_networks:
                if ip in network:
                    return False
        except ValueError:
            continue

    return True


# Domains that are obviously not commerce sites
_NON_COMMERCE_DOMAINS = {
    "google.com", "gmail.com", "youtube.com", "facebook.com", "twitter.com",
    "x.com", "instagram.com", "linkedin.com", "reddit.com", "wikipedia.org",
    "github.com", "stackoverflow.com", "calendar.google.com", "docs.google.com",
    "drive.google.com", "notion.so", "slack.com", "discord.com", "twitch.tv",
    "netflix.com", "spotify.com", "tiktok.com", "pinterest.com", "medium.com",
}


def _check_commerce_site(metadata: dict) -> None:
    """Raise ValueError if the site doesn't look like a commerce site."""
    url = metadata.get("url", "")
    hostname = urlparse(url).hostname or ""
    domain = hostname.replace("www.", "").lower()

    # Block known non-commerce domains
    if domain in _NON_COMMERCE_DOMAINS:
        raise ValueError(
            "This website is not a commerce site. The benchmark is designed for "
            "e-commerce, food delivery, grocery, and similar shopping/ordering websites."
        )

    # For everything else, let GPT-4o decide if it's commerce or not


def generate_tasks(metadata: dict) -> list[dict]:
    """Call GPT-4o to generate 3 benchmark tasks for a website.

    Uses response_format={"type": "json_object"}.
    Returns list of dicts with keys: id, label, goal.
    Raises ValueError if the site is not a commerce site.
    """
    _check_commerce_site(metadata)
    client = OpenAI()

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

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content

    # Strip markdown code fences as safety measure
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    data = json.loads(raw)

    # GPT-4o may reject non-commerce sites
    if "error" in data:
        raise ValueError(data["error"])

    tasks_raw = data.get("tasks", [])

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

    Validates the URL, fetches HTML via aiohttp with 5s timeout, checks
    Content-Type is text/html, extracts metadata, and calls generate_tasks.

    Raises:
        ValueError: for invalid URL or non-HTML content type.
        ConnectionError: for fetch failures (network errors, bad status codes).
    """
    if not validate_url(url):
        raise ValueError(f"Invalid or disallowed URL: {url}")

    timeout = aiohttp.ClientTimeout(total=10)
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
    return generate_tasks(metadata)
