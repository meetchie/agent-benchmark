"""Site mappings: loading, validation and ``{{param}}`` interpolation.

A mapping is the JSON document that describes one site for the Rindler arm:

    {
      "site_id": "vhlistings",
      "domain": "vhlistings.com",
      "screens":  {name: {"url_pattern": regex, "available_actions": [...], ...}},
      "actions":  {name: {"description"?, "params"?, "steps": [...],
                          "target_screen"?, "stays_on_screen"?, "sets_context"?}},
      "context_extractors"?: {name: {"steps": [...]}},
      "interrupt_handlers"?: [{"detect": selector, "detect_timeout_ms"?, "dismiss": [...]}],
      "page_extractor"?: "() => {...}",       # JS run with page.evaluate after each action
      "defaults"?: {name: value}               # fallback values for {{name}} placeholders
    }

The format is the one the March 2026 seeds used (server/mappings/*.sql), plus two optional keys for
the local interpreter: ``defaults`` and an action's ``sets_context`` (see ``Mapping.sets_context``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping as MappingType
from urllib.parse import urlsplit

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"

STEP_ACTIONS = frozenset({"navigate", "click", "type", "select", "extract", "wait", "press_key", "script"})
FALLBACK_TYPES = frozenset({"css", "xpath", "text", "text_exact", "role", "label", "placeholder"})
WAIT_STRATEGIES = frozenset({"selector_visible", "delay", "network_idle"})

# Tools every mapping gets, whatever its actions are.
SESSION_TOOLS = ("start_session", "close_session")

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?::\s*([a-z_]+)\s*)?\}\}")


class MappingError(ValueError):
    """A mapping file is missing, unreadable or does not follow the format."""


def slugify(value: str) -> str:
    """'Smart & Final' -> 'smart-final', 'Target' -> 'target'."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower())
    return slug.strip("-")


_FILTERS = {"slug": slugify, "lower": lambda v: str(v).lower(), "upper": lambda v: str(v).upper()}


def stringify(value: Any) -> str:
    """Render a tool argument the way it goes into a selector or URL.

    Booleans become ``true``/``false`` and whole floats lose their ``.0``, so a
    quantity of 2 is "2" whether the model sent 2 or 2.0.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if value is None:
        return ""
    return str(value)


def interpolate(template: str, values: MappingType[str, Any]) -> str:
    """Replace ``{{name}}`` (and ``{{name:slug}}``) with values; unknown names stay as written."""
    if not template or "{{" not in template:
        return template

    def repl(match: re.Match) -> str:
        name, filt = match.group(1), match.group(2)
        if name not in values:
            return match.group(0)
        text = stringify(values[name])
        if filt:
            fn = _FILTERS.get(filt)
            if fn is None:
                return match.group(0)
            text = fn(text)
        return text

    return _PLACEHOLDER.sub(repl, template)


def placeholders(template: str) -> set[str]:
    return {m.group(1) for m in _PLACEHOLDER.finditer(template or "")}


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def domain_matches(host: str, domain: str) -> bool:
    """True when ``host`` is ``domain`` or one of its subdomains (www.shipt.com ~ shipt.com)."""
    host, domain = host.lower().rstrip("."), domain.lower().rstrip(".")
    return bool(host) and (host == domain or host.endswith("." + domain))


@dataclass(frozen=True)
class Mapping:
    """A validated site mapping. ``raw`` is the JSON document as loaded."""

    raw: dict[str, Any]
    path: Path | None = None
    site_id: str = field(init=False)
    domain: str = field(init=False)

    def __post_init__(self) -> None:
        problems = validate_mapping(self.raw)
        if problems:
            where = f" ({self.path})" if self.path else ""
            raise MappingError(f"invalid mapping{where}:\n  - " + "\n  - ".join(problems))
        object.__setattr__(self, "site_id", str(self.raw.get("site_id") or self.raw["domain"]))
        object.__setattr__(self, "domain", str(self.raw["domain"]).lower())

    @property
    def screens(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("screens") or {}

    @property
    def actions(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("actions") or {}

    @property
    def context_extractors(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("context_extractors") or {}

    @property
    def interrupt_handlers(self) -> list[dict[str, Any]]:
        return list(self.raw.get("interrupt_handlers") or [])

    @property
    def page_extractor(self) -> str | None:
        return self.raw.get("page_extractor") or None

    @property
    def defaults(self) -> dict[str, Any]:
        return dict(self.raw.get("defaults") or {})

    def sets_context(self, action: str) -> dict[str, str]:
        """Context keys an action writes after it succeeds, as templates over its params.

        Example (shipt): ``"sets_context": {"store": "{{store}}", "store_slug": "{{store:slug}}"}``
        so a later ``{{store_slug}}`` in search_products resolves to the chosen store.
        """
        return dict(self.actions.get(action, {}).get("sets_context") or {})

    def global_actions(self) -> list[str]:
        """Actions valid on every screen: start_session, plus update_address if the mapping has it."""
        out = ["start_session"]
        if "update_address" in self.actions:
            out.append("update_address")
        return out

    def matches_url(self, url: str) -> bool:
        return domain_matches(host_of(url), self.domain)


def _check_steps(steps: Any, where: str, problems: list[str]) -> None:
    if not isinstance(steps, list):
        problems.append(f"{where}: steps must be a list")
        return
    for i, step in enumerate(steps):
        label = f"{where} step {i}"
        if not isinstance(step, dict):
            problems.append(f"{label}: must be an object")
            continue
        action = step.get("action")
        if action not in STEP_ACTIONS:
            problems.append(f"{label}: unknown action {action!r}")
            continue
        if action == "navigate" and not step.get("url"):
            problems.append(f"{label}: navigate needs a url")
        if action in ("click", "type", "select") and not step.get("selector"):
            problems.append(f"{label}: {action} needs a selector")
        if action == "wait":
            strategy = step.get("strategy")
            if strategy and strategy not in WAIT_STRATEGIES:
                problems.append(f"{label}: unknown wait strategy {strategy!r}")
            if strategy == "selector_visible" and not step.get("selector"):
                problems.append(f"{label}: selector_visible needs a selector")
        if action == "script" and not step.get("script"):
            problems.append(f"{label}: script needs a script")
        if action == "press_key" and not step.get("value"):
            problems.append(f"{label}: press_key needs a value (the key)")
        timeout = step.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0):
            problems.append(f"{label}: timeout must be a non-negative integer (ms)")
        for j, fb in enumerate(step.get("fallbacks") or []):
            if not isinstance(fb, dict) or fb.get("type") not in FALLBACK_TYPES or not fb.get("selector"):
                problems.append(f"{label} fallback {j}: needs a type in {sorted(FALLBACK_TYPES)} and a selector")


def validate_mapping(raw: Any) -> list[str]:
    """Every problem with a mapping document, as readable strings (empty list = valid)."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        return ["mapping must be a JSON object"]
    if not raw.get("domain") or not isinstance(raw.get("domain"), str):
        problems.append("domain is required")
    screens = raw.get("screens")
    actions = raw.get("actions")
    if not isinstance(screens, dict) or not screens:
        problems.append("screens must be a non-empty object")
        screens = {}
    if not isinstance(actions, dict) or not actions:
        problems.append("actions must be a non-empty object")
        actions = {}

    for name in actions:
        if name in SESSION_TOOLS or name == "done":
            problems.append(f"action name {name!r} is reserved")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", str(name)):
            problems.append(f"action name {name!r} is not a valid tool name")

    for name, screen in screens.items():
        if not isinstance(screen, dict):
            problems.append(f"screen {name}: must be an object")
            continue
        pattern = screen.get("url_pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"screen {name}: bad url_pattern {pattern!r}: {exc}")
        for action in screen.get("available_actions") or []:
            if action not in actions and action not in ("start_session", "update_address"):
                problems.append(f"screen {name}: available action {action!r} is not defined")

    for name, action in actions.items():
        if not isinstance(action, dict):
            problems.append(f"action {name}: must be an object")
            continue
        target = action.get("target_screen")
        if target and target not in screens:
            problems.append(f"action {name}: target_screen {target!r} is not a screen")
        params = action.get("params") or {}
        if not isinstance(params, dict):
            problems.append(f"action {name}: params must be an object")
        _check_steps(action.get("steps", []), f"action {name}", problems)
        sets = action.get("sets_context") or {}
        if not isinstance(sets, dict) or not all(isinstance(v, str) for v in sets.values()):
            problems.append(f"action {name}: sets_context must map names to template strings")

    for name, extractor in (raw.get("context_extractors") or {}).items():
        if not isinstance(extractor, dict):
            problems.append(f"context extractor {name}: must be an object")
            continue
        _check_steps(extractor.get("steps", []), f"context extractor {name}", problems)

    for i, handler in enumerate(raw.get("interrupt_handlers") or []):
        if not isinstance(handler, dict) or not handler.get("detect"):
            problems.append(f"interrupt handler {i}: needs a detect selector")
            continue
        _check_steps(handler.get("dismiss", []), f"interrupt handler {i}", problems)

    extractor = raw.get("page_extractor")
    if extractor is not None and not isinstance(extractor, str):
        problems.append("page_extractor must be a string of JavaScript")
    defaults = raw.get("defaults")
    if defaults is not None and not isinstance(defaults, dict):
        problems.append("defaults must be an object")
    return problems


def mapping_paths(mappings_dir: Path | str = MAPPINGS_DIR) -> list[Path]:
    return sorted(Path(mappings_dir).glob("*.json"))


def load_mapping(
    source: str | Path | MappingType[str, Any] | Mapping,
    *,
    page_extractor: str | Path | None = None,
    mappings_dir: Path | str = MAPPINGS_DIR,
) -> Mapping:
    """Load a mapping from a dict, a JSON file path, or a site name in ``mappings_dir``.

    ``page_extractor`` replaces the mapping's page_extractor: either JavaScript source
    or a path to a ``.js`` file holding it.
    """
    if isinstance(source, Mapping):
        raw, path = dict(source.raw), source.path
    elif isinstance(source, MappingType):
        raw, path = dict(source), None
    else:
        path = Path(source)
        if not path.suffix and not path.exists():
            path = Path(mappings_dir) / f"{source}.json"
        if not path.is_file():
            known = ", ".join(p.stem for p in mapping_paths(mappings_dir)) or "none"
            raise MappingError(f"no mapping file {path} (known sites: {known})")
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise MappingError(f"cannot read mapping {path}: {exc}") from exc

    if page_extractor is not None:
        candidate = Path(str(page_extractor))
        if str(page_extractor).endswith(".js") and candidate.is_file():
            raw["page_extractor"] = candidate.read_text()
        else:
            raw["page_extractor"] = str(page_extractor)
    return Mapping(raw, path)


def find_mapping_for_url(url: str, mappings_dir: Path | str = MAPPINGS_DIR) -> Mapping | None:
    """The mapping in ``mappings_dir`` whose domain matches the URL's host, if any."""
    host = host_of(url)
    best: Mapping | None = None
    for path in mapping_paths(mappings_dir):
        mapping = load_mapping(path)
        if domain_matches(host, mapping.domain):
            # Prefer the most specific domain (shop.example.com over example.com).
            if best is None or len(mapping.domain) > len(best.domain):
                best = mapping
    return best
