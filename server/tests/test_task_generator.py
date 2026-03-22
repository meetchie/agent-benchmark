"""Tests for task_generator.py"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from task_generator import (
    extract_metadata,
    fetch_and_generate,
    generate_tasks,
    validate_url,
)

# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Acme Store</title>
  <meta name="description" content="Shop the best deals online.">
  <style>body { color: red; }</style>
  <script>console.log('hi');</script>
  <noscript>Please enable JavaScript.</noscript>
</head>
<body>
  <h1>Welcome to Acme</h1>
  <p>Find great products here.</p>
</body>
</html>
"""


def test_extract_metadata_from_html():
    result = extract_metadata(SAMPLE_HTML, "https://acme.com")

    assert result["title"] == "Acme Store"
    assert result["description"] == "Shop the best deals online."
    assert result["url"] == "https://acme.com"

    # Visible text should NOT contain script/style/noscript content
    assert "console.log" not in result["visible_text"]
    assert "color: red" not in result["visible_text"]
    assert "Please enable JavaScript" not in result["visible_text"]

    # Should contain real page text
    assert "Welcome to Acme" in result["visible_text"]
    assert "Find great products here" in result["visible_text"]


def test_extract_metadata_missing_tags():
    html = "<html><body><p>Just text.</p></body></html>"
    result = extract_metadata(html, "https://example.com")

    assert result["title"] == ""
    assert result["description"] == ""
    assert "Just text." in result["visible_text"]
    assert result["url"] == "https://example.com"


def test_extract_metadata_visible_text_truncated():
    # Build an HTML body with >1000 chars of text
    long_text = "word " * 300  # 1500 chars
    html = f"<html><body><p>{long_text}</p></body></html>"
    result = extract_metadata(html, "https://example.com")

    assert len(result["visible_text"]) <= 1000


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


def test_validate_url_accepts_https():
    assert validate_url("https://www.example.com") is True


def test_validate_url_accepts_http():
    assert validate_url("http://example.com/path?q=1") is True


def test_validate_url_rejects_private_ip():
    assert validate_url("http://127.0.0.1") is False
    assert validate_url("http://10.0.0.1") is False
    assert validate_url("http://192.168.1.100") is False
    assert validate_url("http://169.254.1.1") is False


def test_validate_url_rejects_docker_range():
    """172.16.0.0/12 (Docker default bridge) must be blocked."""
    assert validate_url("http://172.16.0.1") is False
    assert validate_url("http://172.31.255.255") is False


def test_validate_url_rejects_cgnat():
    """100.64.0.0/10 (CGNAT / cloud metadata) must be blocked."""
    assert validate_url("http://100.64.0.1") is False
    assert validate_url("http://100.100.100.100") is False


def test_validate_url_rejects_zero_network():
    """0.0.0.0/8 must be blocked."""
    assert validate_url("http://0.0.0.0") is False


def test_validate_url_rejects_ipv6_loopback():
    """IPv6 loopback ::1 must be blocked."""
    assert validate_url("http://[::1]") is False


def test_validate_url_rejects_localhost_hostname():
    """The hostname 'localhost' must be blocked."""
    assert validate_url("http://localhost") is False
    assert validate_url("http://localhost:8080") is False


def test_validate_url_rejects_metadata_endpoint():
    """Cloud metadata endpoints must be blocked."""
    assert validate_url("http://metadata.google.internal") is False


def test_validate_url_resolves_dns():
    """Hostnames that resolve to private IPs must be blocked."""
    import socket
    with patch("task_generator.socket.getaddrinfo",
               return_value=[(socket.AF_INET, None, None, None, ("127.0.0.1", 0))]):
        assert validate_url("https://evil.example.com") is False


def test_validate_url_rejects_non_http():
    assert validate_url("ftp://example.com") is False
    assert validate_url("file:///etc/passwd") is False
    assert validate_url("javascript:alert(1)") is False


def test_validate_url_rejects_empty():
    assert validate_url("") is False
    assert validate_url("not-a-url") is False


# ---------------------------------------------------------------------------
# generate_tasks
# ---------------------------------------------------------------------------


def _make_openai_response(tasks: list[dict]) -> MagicMock:
    """Build a minimal mock of an OpenAI ChatCompletion response."""
    content = json.dumps({"tasks": tasks})
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_generate_tasks_returns_three_tasks():
    raw_tasks = [
        {"label": "Task A", "goal": "Step 1\nStep 2\nVerify done."},
        {"label": "Task B", "goal": "Step 1\nStep 2\nVerify done."},
        {"label": "Task C", "goal": "Step 1\nStep 2\nVerify done."},
    ]
    mock_response = _make_openai_response(raw_tasks)

    metadata = {
        "title": "Acme Store",
        "description": "Shop online.",
        "visible_text": "Welcome to Acme.",
        "url": "https://acme.com",
    }

    with patch("task_generator.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        tasks = generate_tasks(metadata)

    assert len(tasks) == 3
    for i, task in enumerate(tasks):
        assert task["id"] == i + 1
        assert "label" in task
        assert "goal" in task
    assert tasks[0]["label"] == "Task A"
    assert tasks[1]["label"] == "Task B"
    assert tasks[2]["label"] == "Task C"


def test_generate_tasks_truncates_to_three():
    """If the model returns more than 3 tasks, only the first 3 are kept."""
    raw_tasks = [
        {"label": f"Task {i}", "goal": f"Do thing {i}."}
        for i in range(5)
    ]
    mock_response = _make_openai_response(raw_tasks)

    metadata = {
        "title": "Site Shop",
        "description": "Online store",
        "visible_text": "Buy products here",
        "url": "https://site.com",
    }

    with patch("task_generator.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        tasks = generate_tasks(metadata)

    assert len(tasks) == 3


def test_generate_tasks_strips_markdown_fences():
    """generate_tasks should handle responses wrapped in markdown code fences."""
    raw_tasks = [
        {"label": "Task A", "goal": "Do A."},
        {"label": "Task B", "goal": "Do B."},
        {"label": "Task C", "goal": "Do C."},
    ]
    fenced_content = "```json\n" + json.dumps({"tasks": raw_tasks}) + "\n```"

    message = MagicMock()
    message.content = fenced_content
    choice = MagicMock()
    choice.message = message
    mock_response = MagicMock()
    mock_response.choices = [choice]

    metadata = {
        "title": "Site Shop",
        "description": "Online store",
        "visible_text": "Buy products here",
        "url": "https://site.com",
    }

    with patch("task_generator.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        tasks = generate_tasks(metadata)

    assert len(tasks) == 3
    assert tasks[0]["label"] == "Task A"


# ---------------------------------------------------------------------------
# fetch_and_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_and_generate_full_flow():
    """Mock both aiohttp and OpenAI; verify the full pipeline."""
    raw_tasks = [
        {"label": "Task A", "goal": "Do A."},
        {"label": "Task B", "goal": "Do B."},
        {"label": "Task C", "goal": "Do C."},
    ]
    mock_oai_response = _make_openai_response(raw_tasks)

    # Build a mock aiohttp response
    mock_http_response = AsyncMock()
    mock_http_response.status = 200
    mock_http_response.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_http_response.text = AsyncMock(return_value=SAMPLE_HTML)
    mock_http_response.__aenter__ = AsyncMock(return_value=mock_http_response)
    mock_http_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_http_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("task_generator.aiohttp.ClientSession", return_value=mock_session),
        patch("task_generator.OpenAI") as MockOpenAI,
    ):
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_oai_response

        tasks = await fetch_and_generate("https://acme.com")

    assert len(tasks) == 3
    assert tasks[0]["label"] == "Task A"
    assert tasks[0]["id"] == 1


@pytest.mark.asyncio
async def test_fetch_and_generate_invalid_url():
    with pytest.raises(ValueError, match="Invalid or disallowed URL"):
        await fetch_and_generate("http://127.0.0.1/admin")


@pytest.mark.asyncio
async def test_fetch_and_generate_non_html_content_type():
    mock_http_response = AsyncMock()
    mock_http_response.status = 200
    mock_http_response.headers = {"Content-Type": "application/json"}
    mock_http_response.__aenter__ = AsyncMock(return_value=mock_http_response)
    mock_http_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_http_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("task_generator.validate_url", return_value=True),
        patch("task_generator.aiohttp.ClientSession", return_value=mock_session),
    ):
        with pytest.raises(ValueError, match="did not return HTML"):
            await fetch_and_generate("https://api.example.com/data")


@pytest.mark.asyncio
async def test_fetch_and_generate_http_error():
    mock_http_response = AsyncMock()
    mock_http_response.status = 404
    mock_http_response.headers = {"Content-Type": "text/html"}
    mock_http_response.__aenter__ = AsyncMock(return_value=mock_http_response)
    mock_http_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_http_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("task_generator.validate_url", return_value=True),
        patch("task_generator.aiohttp.ClientSession", return_value=mock_session),
    ):
        with pytest.raises(ConnectionError, match="HTTP 404"):
            await fetch_and_generate("https://example.com/gone")
