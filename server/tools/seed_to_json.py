"""Convert a March 2026 Rindler seed (.sql) into the mapping JSON the arena runs.

The seeds are Postgres INSERTs whose ``config`` column holds the site mapping as a
quoted JSON literal. This script pulls that literal out, undoes the SQL quoting
('' -> '), parses it, applies the site's override file if there is one, and writes
pretty-printed JSON.

    uv run python tools/seed_to_json.py mappings/seed_vhlistings.sql             # -> mappings/vhlistings.json
    uv run python tools/seed_to_json.py mappings/seed_shipt.sql --check          # exit 1 if the JSON is stale
    uv run python tools/seed_to_json.py --all                                    # every mappings/seed_*.sql

Overrides live in mappings/overrides/<site_id>.json as JSON merge patches (RFC 7386: objects merge,
null deletes a key, anything else replaces). Their ``_notes`` list says why each change was made and
is copied into the output's ``_provenance``, so every difference from the March seed stays visible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent.parent
MAPPINGS_DIR = SERVER_DIR / "mappings"
OVERRIDES_DIR = MAPPINGS_DIR / "overrides"

_INSERT = re.compile(r"INSERT\s+INTO\s+site_configs\b", re.I)


class SeedError(ValueError):
    pass


def _read_sql_string(sql: str, start: int) -> tuple[str, int]:
    """Read the single-quoted SQL literal that opens at sql[start]; return (value, end index)."""
    if sql[start] != "'":
        raise SeedError(f"expected a quote at offset {start}")
    out = []
    i = start + 1
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise SeedError("unterminated string literal")


def extract_config(sql: str) -> tuple[dict[str, Any], int | None]:
    """(mapping dict, version) from the seed's INSERT INTO site_configs statement."""
    match = _INSERT.search(sql)
    if not match:
        raise SeedError("no INSERT INTO site_configs statement")
    pos = sql.index("VALUES", match.end())
    literals = []
    i = pos
    # VALUES ('site id', 'domain', '{...json...}'[::jsonb], version)
    while len(literals) < 3:
        i = sql.index("'", i)
        value, i = _read_sql_string(sql, i)
        literals.append(value)
    config_text = literals[2]
    try:
        config = json.loads(config_text)
    except ValueError as exc:
        raise SeedError(f"config literal is not valid JSON: {exc}") from exc
    version_match = re.match(r"\s*(?:::jsonb)?\s*,\s*(\d+)", sql[i:])
    version = int(version_match.group(1)) if version_match else None
    return config, version


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge patch."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def convert(seed_path: Path, overrides_dir: Path = OVERRIDES_DIR) -> dict[str, Any]:
    config, version = extract_config(seed_path.read_text())
    site_id = config.get("site_id") or seed_path.stem.removeprefix("seed_")
    provenance: dict[str, Any] = {"seed": seed_path.name, "seed_version": version}

    override_path = overrides_dir / f"{site_id}.json"
    if override_path.is_file():
        patch = json.loads(override_path.read_text())
        notes = patch.pop("_notes", [])
        config = merge_patch(config, patch)
        provenance["overrides"] = f"overrides/{override_path.name}"
        provenance["override_notes"] = notes
    return {"_provenance": provenance, **config}


def render(mapping: dict[str, Any]) -> str:
    return json.dumps(mapping, indent=2, ensure_ascii=False) + "\n"


def output_path(seed_path: Path, mapping: dict[str, Any]) -> Path:
    site_id = mapping.get("site_id") or seed_path.stem.removeprefix("seed_")
    return seed_path.parent / f"{site_id}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("seeds", nargs="*", type=Path, help="seed .sql files")
    parser.add_argument("--all", action="store_true", help="convert every mappings/seed_*.sql")
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if any JSON file differs")
    parser.add_argument("--stdout", action="store_true", help="print the JSON instead of writing it")
    args = parser.parse_args(argv)

    seeds = list(args.seeds)
    if args.all:
        seeds += sorted(MAPPINGS_DIR.glob("seed_*.sql"))
    if not seeds:
        parser.error("give seed files or --all")

    stale = 0
    for seed in seeds:
        mapping = convert(seed)
        text = render(mapping)
        if args.stdout:
            sys.stdout.write(text)
            continue
        out = output_path(seed, mapping)
        if args.check:
            current = out.read_text() if out.exists() else None
            if current != text:
                print(f"stale: {out} (re-run tools/seed_to_json.py {seed})")
                stale += 1
            continue
        out.write_text(text)
        print(f"wrote {out}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
