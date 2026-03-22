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

import aiohttp
from bs4 import BeautifulSoup
from openai import OpenAI

PROMPT_TEMPLATE = """You are a benchmark task generator that creates HARD, realistic tasks to stress-test AI browser automation agents on real websites. Your goal is to expose the real weaknesses of AI agents — the kinds of failures that cost businesses money.

Given information about a website, generate exactly 3 benchmark tasks. These tasks should be the kind of thing a real customer does — but that AI agents consistently mess up.

DESIGN PHILOSOPHY:
You are testing for Rindler, a company building infrastructure to make the web agent-ready. The benchmark should expose WHY agents fail today:
- Agents ignore shipping costs and order from multiple stores when one would be cheaper
- Agents can't handle complex forms with dropdowns, modals, date pickers, and address autocomplete
- Agents lose context in multi-step workflows (customize → add to cart → continue shopping → add another)
- Agents don't comparison shop — they grab the first result instead of the best match
- Agents struggle with conditional UI (options that appear only after selecting something else)
- Agents can't handle quantity selectors, size/color matrices, or variant pickers properly
- Agents skip important details like delivery time windows, special instructions, or substitution preferences

RULES:
- Tasks must be specific to THIS website — reference actual features, sections, or products visible on the site
- Each task should have 5-10 concrete steps with SPECIFIC constraints the agent must satisfy
- Include precise numeric constraints (prices, quantities, sizes, distances) that require the agent to compare and choose — not just grab the first result
- Include at least one step that requires interacting with a dropdown, modal, date picker, address form, or other complex UI widget
- Include verification steps that check MULTIPLE criteria (not just "is it in the cart" but "is it the RIGHT item at the RIGHT price in the RIGHT quantity")
- Do NOT include any steps that require login, payment, or submitting sensitive personal information
- Use delivery address "1 Times Square, New York, NY 10036" when address is needed
- Keep labels short (under 60 characters)
- Write goals as multi-line step-by-step instructions
- ALL tasks should be genuinely challenging — no trivial "search and add to cart" tasks

TASK DIFFICULTY LEVELS (generate one of each):
1. MEDIUM: Multi-step with constraints (5-7 steps). Requires comparing options, using filters correctly, and making a specific choice based on criteria.
2. HARD: Complex workflow with state management (7-9 steps). Requires maintaining context across multiple pages, handling complex forms, and satisfying multiple constraints simultaneously.
3. EXPERT: Multi-item workflow with optimization (8-10 steps). Requires building a cart with multiple items that satisfy overlapping constraints (budget limits, same-store preference, delivery windows, etc.)

EXAMPLES of the complexity level expected:

Example 1 (grocery/delivery aggregator — EXPERT):
  label: "Build a $30-$40 cart from a single store"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036. Select the first autocomplete suggestion and confirm.
    Browse available stores and select one that offers free delivery or the lowest delivery fee.
    Add a gallon of whole milk (must be whole, not 2% or skim) to cart.
    Add a dozen large eggs (not medium, not organic unless it's the only option) to cart.
    Add a loaf of sliced bread (white or wheat, not specialty/artisan) to cart.
    Add one bunch of bananas to cart.
    Check the cart subtotal. If under $30, add one more item from the same store. If over $40, remove the most expensive item and find a cheaper alternative.
    Verify: all items are from the SAME store, subtotal is between $30-$40, and delivery fee is shown.

Example 2 (food delivery — HARD):
  label: "Order dinner for 4 under $60 with drinks"
  goal: |
    Set delivery address to 1 Times Square, New York, NY 10036.
    Find a restaurant that is currently open, has a rating of 4+ stars, and offers a delivery time under 45 minutes.
    Order an entree that serves 2 or more people (family size, sharing platter, or equivalent).
    Add a second, different entree suitable for someone who doesn't eat pork (check description/ingredients).
    Add 4 drinks — at least 2 different types (e.g., 2 sodas and 2 waters, not 4 of the same).
    Check if there are any available promotions, coupons, or deals and apply the best one.
    Verify: the order total (before tip) is under $60, there are at least 2 entrees and 4 drinks, delivery time is shown as under 45 minutes.

Example 3 (e-commerce — HARD):
  label: "Find a gift set under $50 with gift wrapping"
  goal: |
    Search for "gift set" or browse the gifts/holiday section.
    Filter results to show only items priced between $25 and $50.
    Sort by customer rating (highest first) or best sellers.
    Select an item that has at least 4-star reviews and is in stock for delivery (not pickup-only or backordered).
    Choose a specific variant if applicable (color, size, scent — pick the most popular or first available option).
    If the site offers gift wrapping or a gift message option, enable it and enter the message "Happy Birthday!".
    Add to cart and verify: the item is in cart, price is between $25-$50, and gift wrapping (if available) is applied.
    Check estimated delivery date — report whether it arrives within 5 business days.

IMPORTANT: This benchmark is ONLY for commerce/transactional websites — e-commerce stores, food delivery, grocery delivery, restaurant ordering, travel booking, ticket purchasing, etc. If the website is NOT a commerce site (e.g., a search engine, social media, news site, productivity tool, email, calendar, wiki, documentation), respond with:
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

    timeout = aiohttp.ClientTimeout(total=5)
    connector = aiohttp.TCPConnector()
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise ConnectionError(
                        f"Failed to fetch the site: HTTP {response.status}"
                    )

                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    raise ValueError(
                        f"URL did not return HTML content. Content-Type: {content_type}"
                    )

                html = await response.text()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise ConnectionError("Failed to fetch the site. It may be unreachable or blocking automated access.") from exc

    metadata = extract_metadata(html, url)
    return generate_tasks(metadata)
