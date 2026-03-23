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
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from openai import OpenAI

PROMPT_TEMPLATE = """You generate benchmark tasks that test whether AI browser agents can actually USE a website properly. The tasks should be very specific instructions — pick exact products the site definitely sells, use exact UI interactions the site requires, and tell the agent exactly what to do. The agent should NOT need to think hard about WHAT to do — the task tells it. The challenge is whether it can actually DO it on the website.

WHAT YOU'RE TESTING:
You're testing the WEBSITE'S compatibility with AI agents, not the agent's intelligence. Tasks should expose where websites break agents:
- Address autocomplete dropdowns that agents can't interact with
- Size/color pickers that require clicking specific swatches or dropdowns
- Quantity selectors (plus/minus buttons, or typing into small number fields)
- Multi-step forms where the next field only appears after filling the previous one
- Modals and popups that block the page until dismissed
- "Add to cart" flows that require selecting mandatory options first
- Customization screens (pizza toppings, burger modifications, product personalization)
- Store/location selection before browsing is allowed

WHAT NOT TO TEST:
- Do NOT ask the agent to make decisions (like "find the cheapest" or "build a $40 cart")
- Do NOT ask the agent to compare options or optimize anything
- Do NOT create vague tasks — be extremely specific about what product to get
- Do NOT test agent reasoning — test website navigation and interaction

RULES:
- Pick SPECIFIC products the site definitely has (based on the site metadata you're given)
- Name exact items: "Large pepperoni pizza" not "a pizza", "Men's black polo shirt in size M" not "a shirt"
- Each task should be a clear chain of specific UI interactions
- Include the exact address "1 Times Square, New York, NY 10036" when delivery address is needed
- Tell the agent exactly what autocomplete suggestion to pick, what size to select, etc.
- End each task with verification: tell the agent exactly what to look for (cart badge count, "in cart" text, slide-out cart panel, etc.)
- Do NOT require login, payment, or sensitive personal info
- Keep labels short (under 60 characters)
- Generate 3 tasks with increasing complexity

DIFFICULTY LEVELS:
1. SIMPLE INTERACTION: Search for a specific item, select its options (size/color), add to cart. Tests basic site navigation and UI widgets (3-5 steps).
2. MULTI-STEP CHAIN: Set address, browse to a section, customize a product (toppings, modifications), add to cart, then add a second specific item. Tests maintaining context across multiple interactions (5-7 steps).
3. FULL WORKFLOW: Set address, select a store/restaurant, add a specific customized item, go back to menu, add a different item with different customizations, verify both items in cart with correct options. Tests the complete shopping flow with multiple products (7-10 steps).

EXAMPLES:

Example 1 (clothing store — SIMPLE):
  label: "Add a men's black polo in size M to cart"
  goal: |
    Go to the Men's section.
    Search for "polo shirt" or browse to Polo Shirts.
    Click on the first black polo shirt result.
    On the product page, select size "M" (Medium).
    Select color "Black" if not already selected.
    Click "Add to Cart" or "Add to Bag".
    VERIFY: Look for a cart icon badge showing "1", or a slide-out cart panel showing the polo shirt in Black, size M.

Example 2 (pizza delivery — MULTI-STEP):
  label: "Order a custom large pizza with 2-liter Coke"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036. Wait for autocomplete dropdown and select the first suggestion.
    Navigate to the Menu section.
    Select "Build Your Own" or "Create Your Own" pizza.
    Choose size: Large. Choose crust: Hand Tossed (or default if not available).
    Add toppings: Pepperoni and Mushrooms. Do NOT add other toppings.
    Click "Add to Order" or "Add to Cart".
    Go back to the menu. Find "Drinks" or "Beverages" section.
    Add a 2-Liter Coca-Cola (regular, not diet or zero).
    VERIFY: Cart should show 2 items — one custom large pizza with pepperoni and mushrooms, and one 2-Liter Coca-Cola.

Example 3 (grocery — FULL WORKFLOW):
  label: "Add 6 Granny Smith apples and whole milk"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036. Wait for autocomplete and select the first suggestion.
    Once stores load, select the first available grocery store.
    Search for "Granny Smith Apples".
    Find loose individual Granny Smith apples (not a pre-bagged item). Set quantity to 6 (or if sold by weight, approximately 3 lbs).
    Add to cart.
    Search for "Whole Milk".
    Find a gallon of Whole milk — must say "Whole" (not 2%, not Skim, not Organic unless only option).
    Add 1 gallon to cart.
    VERIFY: Go to cart. Confirm it shows Granny Smith Apples (qty 6 or ~3 lbs) AND Whole Milk (1 gallon). Cart should show 2 distinct products.

IMPORTANT: This benchmark is ONLY for commerce/transactional websites. If the website is NOT a commerce site (search engine, social media, news, productivity tool, etc.), respond with:
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
    """Validate that a URL uses http/https and is not a private/internal IP.

    Rejects 127.x, 10.x, 192.168.x, 169.254.x ranges.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Check if hostname is an IP address in a private range
    try:
        ip = ipaddress.ip_address(hostname)
        private_networks = [
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),
        ]
        for network in private_networks:
            if ip in network:
                return False
    except ValueError:
        # Not an IP address — hostname is fine
        pass

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

    prompt = PROMPT_TEMPLATE.format(
        title=metadata.get("title", ""),
        description=metadata.get("description", ""),
        visible_text=metadata.get("visible_text", ""),
        url=metadata.get("url", ""),
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

    timeout = aiohttp.ClientTimeout(total=5)
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise ConnectionError(
                        f"Failed to fetch {url}: HTTP {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    raise ValueError(
                        f"URL did not return HTML content. Content-Type: {content_type}"
                    )

                html = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ConnectionError(f"Failed to fetch {url}: {exc}") from exc

    metadata = extract_metadata(html, url)
    return generate_tasks(metadata)
