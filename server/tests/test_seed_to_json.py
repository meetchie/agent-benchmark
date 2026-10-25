"""tools/seed_to_json.py: the March seeds convert into exactly the committed mapping JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.seed_to_json import MAPPINGS_DIR, SeedError, convert, extract_config, merge_patch, output_path, render, main

SEEDS = sorted(MAPPINGS_DIR.glob("seed_*.sql"))


def test_there_are_seeds():
    assert {p.name for p in SEEDS} == {"seed_shipt.sql", "seed_vhlistings.sql"}


@pytest.mark.parametrize("seed", SEEDS, ids=lambda p: p.stem)
def test_committed_json_is_the_converted_seed(seed):
    mapping = convert(seed)
    out = output_path(seed, mapping)
    assert out.read_text() == render(mapping), f"{out} is stale; run tools/seed_to_json.py --all"


@pytest.mark.parametrize("seed", SEEDS, ids=lambda p: p.stem)
def test_json_differs_from_the_seed_only_by_its_override(seed):
    config, version = extract_config(seed.read_text())
    committed = json.loads(output_path(seed, config).read_text())
    provenance = committed.pop("_provenance")
    assert provenance["seed"] == seed.name and provenance["seed_version"] == version
    override_file = MAPPINGS_DIR / "overrides" / f"{config['site_id']}.json"
    patch = json.loads(override_file.read_text())
    notes = patch.pop("_notes")
    assert notes and provenance["override_notes"] == notes
    assert committed == merge_patch(config, patch)
    # Every top-level key the override touches is explained in a note.
    for key in patch:
        assert any(key in note for note in notes), f"override key {key!r} has no note"


def test_versions_match_the_march_seeds():
    versions = {p.stem: extract_config(p.read_text())[1] for p in SEEDS}
    assert versions == {"seed_shipt": 1, "seed_vhlistings": 25}


def test_extract_config_unescapes_sql_quotes_and_keeps_backslashes():
    sql = (
        "-- comment with 'quotes'\n"
        "INSERT INTO users (id) VALUES ('u');\n"
        "INSERT INTO site_configs (site_id, domain, config, version) VALUES (\n"
        "  'id-1', 'x.com',\n"
        "  '{\"site_id\": \"x\", \"sel\": \"li[role=''option'']\", \"re\": \"x\\\\.com/$\"}'::jsonb,\n"
        "  7\n) ON CONFLICT DO NOTHING;\n"
    )
    config, version = extract_config(sql)
    assert config == {"site_id": "x", "sel": "li[role='option']", "re": "x\\.com/$"}
    assert version == 7


def test_extract_config_errors():
    with pytest.raises(SeedError):
        extract_config("SELECT 1;")
    with pytest.raises(SeedError):
        extract_config("INSERT INTO site_configs VALUES ('a', 'b', 'not json', 1);")


def test_merge_patch():
    assert merge_patch({"a": 1, "b": {"c": 2, "d": 3}}, {"b": {"c": None, "e": 4}, "f": [1]}) == {
        "a": 1, "b": {"d": 3, "e": 4}, "f": [1]
    }
    assert merge_patch({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_check_mode_passes_on_the_committed_files(capsys):
    assert main(["--all", "--check"]) == 0
