"""A site is three files that share a name: a Rindler mapping, an optional page
extractor and the task instructions.

    cli/mappings/<site>.json      the site's screens and actions (Rindler arm only)
    cli/extractors/<site>.js      JavaScript that summarises a page for the model (optional)
    cli/instructions/<site>.yaml  the tasks both arms are given

The mapping is loaded and checked by the same code the arena uses (rindler_local), so the
CLI's tool list is exactly what the arena would build from the same file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rindler_local import Mapping, MappingError, build_tools, load_mapping

CLI_DIR = Path(__file__).resolve().parent.parent
MAPPINGS_DIR = CLI_DIR / "mappings"
INSTRUCTIONS_DIR = CLI_DIR / "instructions"
EXTRACTORS_DIR = CLI_DIR / "extractors"

DEFAULT_MAX_STEPS = 25
REQUIRED_TASK_FIELDS = ("id", "name", "goal", "start_url", "success_criteria")

# Words that would tell the BrowserUse arm something about the Rindler arm.
LEAK_WORDS = ("rindler",)


class SiteError(Exception):
    """A site file is missing or malformed. The message says what to fix."""


@dataclass
class Site:
    name: str
    mapping: Mapping
    instructions: dict[str, Any]
    extractor: Path | None

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return self.instructions["tasks"]

    @property
    def domain(self) -> str:
        return str(self.instructions.get("domain") or self.mapping.domain)


def _check_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name or "") or ".." in name:
        raise SiteError(f"bad site name {name!r}: use the file name under mappings/ without .json")


def find_extractor(name: str, site_id: str, cli_dir: Path = CLI_DIR) -> Path | None:
    """cli/extractors/<name>.js, else the one named after the mapping's site_id.

    prose-hard.json is a copy of prose.json (site_id "prose"), so it shares prose.js.
    """
    for stem in (name, site_id):
        path = cli_dir / "extractors" / f"{stem}.js"
        if path.is_file():
            return path
    return None


def load_site_mapping(name: str, cli_dir: Path = CLI_DIR) -> tuple[Mapping, Path | None]:
    _check_name(name)
    path = cli_dir / "mappings" / f"{name}.json"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (cli_dir / "mappings").glob("*.json"))) or "none"
        raise SiteError(f"no mapping file {path} (sites with a mapping: {known})")
    try:
        draft = load_mapping(path)
    except MappingError as exc:
        raise SiteError(str(exc)) from exc
    extractor = find_extractor(name, draft.site_id, cli_dir)
    if extractor is None:
        return draft, None
    try:
        return load_mapping(path, page_extractor=extractor), extractor
    except MappingError as exc:
        raise SiteError(str(exc)) from exc


def load_instructions(name: str, cli_dir: Path = CLI_DIR) -> dict[str, Any]:
    _check_name(name)
    path = cli_dir / "instructions" / f"{name}.yaml"
    if not path.is_file():
        raise SiteError(f"no instructions file {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise SiteError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list) or not data["tasks"]:
        raise SiteError(f"{path} must have a non-empty 'tasks' list")

    seen: set[str] = set()
    for i, task in enumerate(data["tasks"]):
        if not isinstance(task, dict):
            raise SiteError(f"{path}: task {i} must be a mapping")
        missing = [f for f in REQUIRED_TASK_FIELDS if not task.get(f)]
        if missing:
            raise SiteError(f"{path}: task {i} is missing {', '.join(missing)}")
        if task["id"] in seen:
            raise SiteError(f"{path}: duplicate task id {task['id']!r}")
        seen.add(task["id"])
        steps = task.setdefault("max_steps", DEFAULT_MAX_STEPS)
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
            raise SiteError(f"{path}: task {task['id']!r} max_steps must be a positive integer")
    return data


def load_site(name: str, cli_dir: Path = CLI_DIR) -> Site:
    mapping, extractor = load_site_mapping(name, cli_dir)
    return Site(name=name, mapping=mapping, instructions=load_instructions(name, cli_dir), extractor=extractor)


def select_tasks(tasks: list[dict[str, Any]], wanted: list[str] | None) -> list[dict[str, Any]]:
    """All tasks when ``wanted`` is None, else only those ids (kept in file order).

    Unknown ids are an error, and so is an empty list: it means the ids were lost on the
    way here, not that every task should run.
    """
    if wanted is None:
        return list(tasks)
    if not wanted:
        raise SiteError(f"no task ids given. Known: {', '.join(t['id'] for t in tasks)}")
    known = {t["id"] for t in tasks}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise SiteError(f"unknown task id(s): {', '.join(unknown)}. Known: {', '.join(t['id'] for t in tasks)}")
    return [t for t in tasks if t["id"] in set(wanted)]


def effective_max_steps(task: dict[str, Any], override: int | None = None) -> int:
    """The step budget both arms get for one task: --max-steps, else the task's own."""
    return int(override) if override else int(task.get("max_steps") or DEFAULT_MAX_STEPS)


def tool_name_leaks(text: str, mapping: Mapping) -> list[str]:
    """Rindler tool names (snake_case actions, the session tools) and brand words found in ``text``.

    The BrowserUse arm gets the task's goal verbatim, so a goal that said "call
    view_accessories" would hand it the Rindler arm's interface. Plain English action
    names such as "checkout" are not flagged, only names with an underscore.
    """
    names = {t["name"] for t in build_tools(mapping)}
    names |= {a for a in mapping.actions}
    hits = []
    for word in sorted(n for n in names if "_" in n or "-" in n):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text, re.I):
            hits.append(word)
    for word in LEAK_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text, re.I):
            hits.append(word)
    return hits


def task_text_leaks(tasks: list[dict[str, Any]], mapping: Mapping) -> dict[str, list[str]]:
    """{task id: leaked names} for every task whose goal mentions Rindler's interface."""
    out = {}
    for task in tasks:
        hits = tool_name_leaks(str(task["goal"]), mapping)
        if hits:
            out[task["id"]] = hits
    return out
