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

PROMPT_TEMPLATE = """You are a benchmark task generator for testing browser automation agents on real websites.

Given information about a website, generate exactly 3 benchmark tasks that an AI browser agent should be able to complete on this site. Each task should test a different capability.

RULES:
- Tasks must be specific to THIS website — reference actual features, sections, or products visible on the site
- Each task should have 3-5 concrete steps that the agent must follow in sequence
- Include a verification step at the end (e.g., "Verify success by checking that the cart shows the item")
- Tasks should be realistic things a real user would do on this site
- Vary the difficulty: one easy (navigate + read), one medium (search + interact), one hard (multi-step workflow)
- Do NOT include any steps that require login, payment, or submitting personal information beyond an address
- Keep labels short (under 60 characters)
- Write goals as multi-line step-by-step instructions

EXAMPLES of good tasks (for reference on style and complexity):

Example 1 (e-commerce site):
  label: "Find running shoes in size 10 and add to cart"
  goal: |
    Search for men's running shoes.
    Filter or sort results to find options available in US size 10.
    Add the cheapest available size-10 option to cart.
    Verify success by checking the cart shows the shoes.

Example 2 (food delivery site):
  label: "Order half-and-half pizza with sides"
  goal: |
    Order a large pizza that is half cheese, half pepperoni.
    Also add a large Diet Coke and garlic bread twists (or closest available side).
    Verify success by checking that all items appear in the cart or order summary.

Example 3 (grocery site):
  label: "Add Organic Bananas to cart"
  goal: |
    Set delivery address to 1 Main St, Springfield, IL 62701. Select the first autocomplete result.
    Search for "Organic Bananas" and add the first result to cart.
    Verify success by checking that the cart icon shows a count or an "In cart" indicator appears.

Respond with a JSON object with a "tasks" key containing an array of 3 objects, each with "label" (string) and "goal" (string) fields. No markdown, no explanation.

WEBSITE INFORMATION:
Title: {title}
Description: {description}
Content preview: {visible_text}
URL: {url}
"""


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


def generate_tasks(metadata: dict) -> list[dict]:
    """Call GPT-4o to generate 3 benchmark tasks for a website.

    Uses response_format={"type": "json_object"}.
    Returns list of dicts with keys: id, label, goal.
    """
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
