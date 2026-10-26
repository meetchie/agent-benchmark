"""Tests for task_generator.py"""

import asyncio
import ipaddress
import json
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

import llm
from task_generator import (
    TASKS_SCHEMA,
    _is_internal,
    check_url,
    extract_metadata,
    fetch_and_generate,
    generate_tasks,
    validate_url,
)
from tests.fakes import install_fake_anthropic, refusal_response, text_response

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


# check_url: the async twin of validate_url, with a reason and a lookup off the event loop

PUBLIC_ADDRINFO = [(2, None, None, None, ("93.184.216.34", 0))]


def _addrinfo(address):
    return [(2, None, None, None, (address, 0))]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1",
    "http://127.0.0.1:8000/admin",
    "http://10.0.0.1",
    "http://192.168.1.100",
    "http://169.254.169.254/latest/meta-data",  # cloud metadata, link-local
    "http://172.16.0.1",
    "http://172.31.255.255",
    "http://100.64.0.1",
    "http://100.100.100.100",
    "http://0.0.0.0",
    "http://[::1]",
    "http://[fe80::1]",
    "http://[fc00::1]",
    "http://[::]",                       # unspecified: connects to this machine
    "http://[::ffff:127.0.0.1]:8000/health",  # IPv4-mapped loopback
    "http://[::ffff:7f00:1]/",           # the same, written in hex
    "http://[::ffff:10.0.0.1]",
    "http://[::ffff:169.254.169.254]",
    "http://[::127.0.0.1]",              # IPv4-compatible (deprecated form)
    "http://[2002:7f00:1::]",            # 6to4 of 127.0.0.1
    "http://[2002:a00:1::]",             # 6to4 of 10.0.0.1
    "http://224.0.0.1",                  # multicast
    "http://[ff02::1]",
    "http://240.0.0.1",                  # reserved
    "http://localhost",
    "http://localhost:8080",
    "http://metadata.google.internal",
    "ftp://example.com",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "",
    "not-a-url",
])
async def test_check_url_keeps_blocking_what_the_ssrf_guard_blocked(url):
    # Literal addresses are parsed, not looked up, and the internal names are refused
    # by name, so none of these needs the network.
    with pytest.raises(ValueError) as excinfo:
        await check_url(url)
    assert str(excinfo.value) == f"Invalid or disallowed URL: {url}"
    assert validate_url(url) is False  # the blocking twin agrees


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "192.168.0.7", "169.254.169.254", "100.64.0.9", "::1", "fd00::1",
    "::ffff:127.0.0.1", "::ffff:192.168.0.7", "::", "fe80::1%en0",
])
async def test_check_url_blocks_a_host_that_resolves_to_an_internal_address(address):
    with patch("task_generator.socket.getaddrinfo", return_value=_addrinfo(address)):
        with pytest.raises(ValueError, match="Invalid or disallowed URL: https://evil.example.com"):
            await check_url("https://evil.example.com")


async def test_check_url_blocks_a_host_when_any_one_address_is_internal():
    mixed = PUBLIC_ADDRINFO + _addrinfo("10.0.0.5")
    with patch("task_generator.socket.getaddrinfo", return_value=mixed):
        with pytest.raises(ValueError, match="disallowed"):
            await check_url("https://rebinding.example.com")


async def test_check_url_allows_a_public_host():
    with patch("task_generator.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO):
        assert await check_url("https://www.example.com/shop?q=1") is None


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946", "::ffff:93.184.216.34"])
async def test_check_url_allows_public_addresses_in_every_form(address):
    with patch("task_generator.socket.getaddrinfo", return_value=_addrinfo(address)):
        assert await check_url("https://www.example.com/") is None


class _IPv6AddressOnOlderPython(ipaddress.IPv6Address):
    """An IPv6Address as Debian 12's Python 3.11.2 has it: an IPv4-mapped address lies
    inside ::/8, which that version calls reserved whatever IPv4 address it carries."""

    @property
    def is_reserved(self):
        return self in ipaddress.ip_network("::/8") or super().is_reserved


def test_an_ipv4_mapped_address_is_judged_by_its_ipv4_address_on_every_python():
    public = _IPv6AddressOnOlderPython("::ffff:93.184.216.34")
    assert public.is_reserved  # what the guard must not go by
    assert _is_internal(public) is False
    assert _is_internal(_IPv6AddressOnOlderPython("::ffff:127.0.0.1")) is True
    assert _is_internal(_IPv6AddressOnOlderPython("::ffff:10.0.0.1")) is True
    assert _is_internal(_IPv6AddressOnOlderPython("::127.0.0.1")) is True  # IPv4-compatible, not mapped


async def test_check_url_says_when_a_host_does_not_resolve():
    import socket

    with patch("task_generator.socket.getaddrinfo", side_effect=socket.gaierror(8, "nodename nor servname provided")):
        with pytest.raises(ValueError) as excinfo:
            await check_url("https://no-such-shop.example/products")
    assert str(excinfo.value) == "Could not resolve this host: no-such-shop.example"
    assert "disallowed" not in str(excinfo.value)


async def test_check_url_treats_an_unencodable_host_name_as_unresolvable():
    with pytest.raises(ValueError, match="Could not resolve this host"):
        await check_url("http://bad..name.example/")


async def test_check_url_does_not_block_the_event_loop():
    """The DNS lookup is blocking; it must run off the loop so other requests keep moving."""
    import threading
    import time

    seen = {}

    def slow_lookup(host, port, *args, **kwargs):
        seen["thread"] = threading.current_thread()
        time.sleep(0.4)
        return PUBLIC_ADDRINFO

    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.02)

    watcher = asyncio.create_task(ticker())
    try:
        with patch("task_generator.socket.getaddrinfo", slow_lookup):
            await check_url("https://slow-dns.example.com")
    finally:
        watcher.cancel()
    assert seen["thread"] is not threading.main_thread()
    assert len(ticks) > 8  # ~0.4 s of lookup at 20 ms ticks


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


METADATA = {
    "title": "Acme Store",
    "description": "Shop online.",
    "visible_text": "Welcome to Acme.",
    "url": "https://acme.com",
}


def _tasks_payload(tasks: list[dict]) -> dict:
    return {"tasks": tasks}


def test_generate_tasks_returns_three_tasks(monkeypatch):
    raw_tasks = [
        {"label": "Task A", "goal": "Step 1\nStep 2\nVerify done."},
        {"label": "Task B", "goal": "Step 1\nStep 2\nVerify done."},
        {"label": "Task C", "goal": "Step 1\nStep 2\nVerify done."},
    ]
    install_fake_anthropic(monkeypatch, text_response(_tasks_payload(raw_tasks)))

    tasks = generate_tasks(METADATA)

    assert len(tasks) == 3
    for i, task in enumerate(tasks):
        assert task["id"] == i + 1
        assert "label" in task
        assert "goal" in task
    assert tasks[0]["label"] == "Task A"
    assert tasks[1]["label"] == "Task B"
    assert tasks[2]["label"] == "Task C"


def test_generate_tasks_truncates_to_three(monkeypatch):
    """If the model returns more than 3 tasks, only the first 3 are kept."""
    raw_tasks = [
        {"label": f"Task {i}", "goal": f"Do thing {i}."}
        for i in range(5)
    ]
    install_fake_anthropic(monkeypatch, text_response(_tasks_payload(raw_tasks)))

    tasks = generate_tasks(METADATA)

    assert len(tasks) == 3


def test_generate_tasks_strips_markdown_fences(monkeypatch):
    """generate_tasks should handle responses wrapped in markdown code fences."""
    raw_tasks = [
        {"label": "Task A", "goal": "Do A."},
        {"label": "Task B", "goal": "Do B."},
        {"label": "Task C", "goal": "Do C."},
    ]
    fenced_content = "```json\n" + json.dumps({"tasks": raw_tasks}) + "\n```"
    install_fake_anthropic(monkeypatch, text_response(fenced_content))

    tasks = generate_tasks(METADATA)

    assert len(tasks) == 3
    assert tasks[0]["label"] == "Task A"


def test_generate_tasks_asks_for_structured_output_from_the_taskgen_model(monkeypatch):
    calls = install_fake_anthropic(
        monkeypatch, text_response(_tasks_payload([{"label": "A", "goal": "Do A."}]))
    )
    monkeypatch.setenv("BENCHMARK_TASKGEN_MODEL", "claude-haiku-5-5")

    generate_tasks(METADATA)

    (request,) = calls
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert set(request["output_config"]["format"]["schema"]["properties"]) == {"tasks", "error"}
    assert not {"temperature", "top_p", "top_k"} & set(request)
    # The prompt is the unchanged task-design prompt with the site's metadata filled in.
    prompt = request["messages"][0]["content"]
    assert "AGENT FAILURE PATTERNS" in prompt
    assert "Title: Acme Store" in prompt
    assert "URL: https://acme.com" in prompt


def test_generate_tasks_schema_is_accepted_by_the_llm_layer():
    schema = llm.strict_schema(TASKS_SCHEMA)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["tasks"]["items"]["additionalProperties"] is False


def test_generate_tasks_non_commerce_site_raises_value_error(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response({"error": "This website is not a commerce site."}))
    with pytest.raises(ValueError, match="not a commerce site"):
        generate_tasks(METADATA)


def test_generate_tasks_known_non_commerce_domain_never_calls_the_model(monkeypatch):
    calls = install_fake_anthropic(monkeypatch, text_response(_tasks_payload([])))
    with pytest.raises(ValueError, match="not a commerce site"):
        generate_tasks({**METADATA, "url": "https://www.github.com/x"})
    assert calls == []


def test_generate_tasks_empty_task_list_raises_value_error(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response(_tasks_payload([])))
    with pytest.raises(ValueError, match="Could not generate"):
        generate_tasks(METADATA)


def test_generate_tasks_refusal_becomes_a_value_error(monkeypatch):
    """A safety refusal is a 422-style answer for the user, not a server error."""
    install_fake_anthropic(monkeypatch, refusal_response())
    with pytest.raises(ValueError, match="declined"):
        generate_tasks(METADATA)


def test_generate_tasks_api_error_propagates_as_llm_error(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=request), body=None
    )
    install_fake_anthropic(monkeypatch, error)
    with pytest.raises(llm.LLMError) as excinfo:
        generate_tasks(METADATA)
    assert excinfo.value.kind == "api"
    assert excinfo.value.status_code == 401


def test_generate_tasks_truncated_reply_propagates_as_llm_error(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response('{"tasks": [', stop_reason="max_tokens"))
    with pytest.raises(llm.LLMError) as excinfo:
        generate_tasks(METADATA)
    assert excinfo.value.kind == "max_tokens"


def test_generate_tasks_known_commerce_domain_adds_the_note(monkeypatch):
    calls = install_fake_anthropic(
        monkeypatch, text_response(_tasks_payload([{"label": "A", "goal": "Do A."}]))
    )
    generate_tasks({"title": "", "description": "", "visible_text": "", "url": "https://www.amazon.com"})
    assert "confirmed commerce/transactional website" in calls[0]["messages"][0]["content"]


# ---------------------------------------------------------------------------
# fetch_and_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_and_generate_full_flow(monkeypatch):
    """Mock both aiohttp and the model API; verify the full pipeline."""
    raw_tasks = [
        {"label": "Task A", "goal": "Do A."},
        {"label": "Task B", "goal": "Do B."},
        {"label": "Task C", "goal": "Do C."},
    ]
    calls = install_fake_anthropic(monkeypatch, text_response(_tasks_payload(raw_tasks)))

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
        patch("task_generator.check_url"),
        patch("task_generator.aiohttp.ClientSession", return_value=mock_session),
    ):
        tasks = await fetch_and_generate("https://acme.com")

    assert len(tasks) == 3
    assert tasks[0]["label"] == "Task A"
    assert tasks[0]["id"] == 1
    # The page's own title and text reached the prompt.
    assert "Title: Acme Store" in calls[0]["messages"][0]["content"]


def _public_dns(host, *args, **kwargs):
    """Host names resolve to a public address; an address literal stays itself."""
    import ipaddress

    try:
        ipaddress.ip_address(host)
    except ValueError:
        return PUBLIC_ADDRINFO
    return _addrinfo(host)


def _response(status, headers, body=""):
    response = AsyncMock()
    response.status = status
    response.headers = headers
    response.text = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def _session(*responses):
    session = AsyncMock()
    session.get = MagicMock(side_effect=list(responses))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_fetch_and_generate_refuses_a_redirect_to_this_machine():
    """A public page that redirects to 127.0.0.1 must not make the server fetch it."""
    session = _session(_response(302, {"Location": "http://127.0.0.1:8000/health"}))
    with (
        patch("task_generator.socket.getaddrinfo", side_effect=_public_dns),
        patch("task_generator.aiohttp.ClientSession", return_value=session),
    ):
        with pytest.raises(ValueError, match=r"Invalid or disallowed URL: http://127\.0\.0\.1:8000/health"):
            await fetch_and_generate("https://shop.example.com/")
    assert session.get.call_count == 1  # the internal address was never requested
    assert session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_fetch_and_generate_follows_a_public_redirect(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response(_tasks_payload([
        {"label": "A", "goal": "Do A."}, {"label": "B", "goal": "Do B."}, {"label": "C", "goal": "Do C."},
    ])))
    session = _session(
        _response(301, {"Location": "/store"}),
        _response(200, {"Content-Type": "text/html"}, SAMPLE_HTML),
    )
    with (
        patch("task_generator.socket.getaddrinfo", side_effect=_public_dns),
        patch("task_generator.aiohttp.ClientSession", return_value=session),
    ):
        tasks = await fetch_and_generate("https://shop.example.com/")
    assert len(tasks) == 3
    assert [c.args[0] for c in session.get.call_args_list] == [
        "https://shop.example.com/", "https://shop.example.com/store",
    ]


@pytest.mark.asyncio
async def test_fetch_and_generate_stops_an_endless_redirect():
    session = _session(*[_response(302, {"Location": "/again"}) for _ in range(10)])
    with (
        patch("task_generator.socket.getaddrinfo", side_effect=_public_dns),
        patch("task_generator.aiohttp.ClientSession", return_value=session),
    ):
        with pytest.raises(ConnectionError, match="redirected more than 5 times"):
            await fetch_and_generate("https://shop.example.com/")


@pytest.mark.asyncio
async def test_fetch_and_generate_invalid_url():
    with pytest.raises(ValueError, match="Invalid or disallowed URL"):
        await fetch_and_generate("http://127.0.0.1/admin")


@pytest.mark.asyncio
async def test_fetch_and_generate_says_when_the_host_does_not_resolve():
    import socket

    with patch("task_generator.socket.getaddrinfo", side_effect=socket.gaierror(8, "unknown host")):
        with pytest.raises(ValueError, match="Could not resolve this host: nope.example"):
            await fetch_and_generate("https://nope.example/")


@pytest.mark.asyncio
async def test_fetch_and_generate_checks_the_host_of_a_known_shop_too(monkeypatch):
    """A known commerce domain skips the page fetch, not the address check."""
    install_fake_anthropic(monkeypatch, text_response(_tasks_payload([{"label": "A", "goal": "Do A."}])))
    with patch("task_generator.socket.getaddrinfo", return_value=_addrinfo("10.0.0.8")):
        with pytest.raises(ValueError, match="Invalid or disallowed URL"):
            await fetch_and_generate("https://www.target.com")


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
        patch("task_generator.check_url"),
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
        patch("task_generator.check_url"),
        patch("task_generator.aiohttp.ClientSession", return_value=mock_session),
    ):
        with pytest.raises(ConnectionError, match="HTTP 404"):
            await fetch_and_generate("https://example.com/gone")


@pytest.mark.asyncio
async def test_fetch_and_generate_known_commerce_domain_skips_the_fetch(monkeypatch):
    """Known shops block server-side fetches, so the model works from the domain alone."""
    raw_tasks = [{"label": "A", "goal": "Do A."}]
    calls = install_fake_anthropic(monkeypatch, text_response(_tasks_payload(raw_tasks)))
    with (
        patch("task_generator.check_url"),
        patch("task_generator.aiohttp.ClientSession", side_effect=AssertionError("must not fetch")),
    ):
        tasks = await fetch_and_generate("https://www.target.com")
    assert [t["label"] for t in tasks] == ["A"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fetch_and_generate_keeps_the_event_loop_free(monkeypatch):
    """The model call is blocking, so it must not run on the event loop thread."""
    import threading

    seen = {}

    def fake_generate(metadata):
        seen["thread"] = threading.current_thread()
        return [{"id": 1, "label": "A", "goal": "Do A."}]

    with (
        patch("task_generator.check_url"),
        patch("task_generator.generate_tasks", fake_generate),
    ):
        await fetch_and_generate("https://www.target.com")
    assert seen["thread"] is not threading.main_thread()
