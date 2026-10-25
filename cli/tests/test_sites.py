"""Site loading: the mapping gives the tool list, the YAML gives the tasks."""

import pytest

from benchcli import sites
from rindler_local import build_tools


@pytest.fixture(scope="module")
def prose():
    return sites.load_site("prose")


def test_prose_tools_come_from_the_mapping(prose):
    names = [t["name"] for t in build_tools(prose.mapping)]
    # The March CLI listed fixed tool names; these two were missing from its list.
    assert "view_accessories" in names and "view_gift_cards" in names
    assert names == [
        "start_session", "add_to_cart", "go_back", "remove_from_cart", "search_products",
        "view_accessories", "view_cart", "view_gift_cards", "view_product", "close_session",
    ]
    assert set(names) - {"start_session", "close_session"} == set(prose.mapping.actions)


def test_every_screen_action_is_a_defined_tool(prose):
    tools = {t["name"] for t in build_tools(prose.mapping)}
    for screen in prose.mapping.screens.values():
        assert set(screen["available_actions"]) <= tools


def test_prose_extractor_is_loaded_into_the_mapping(prose):
    assert prose.extractor.name == "prose.js"
    assert prose.mapping.page_extractor.lstrip().startswith("//") or "() =>" in prose.mapping.page_extractor


def test_prose_hard_shares_the_prose_extractor():
    hard = sites.load_site("prose-hard")
    assert hard.extractor.name == "prose.js"  # found through the mapping's site_id
    assert hard.mapping.page_extractor


def test_tasks_are_complete_and_get_the_default_budget(prose):
    assert len(prose.tasks) == 10
    for task in prose.tasks:
        assert all(task[f] for f in sites.REQUIRED_TASK_FIELDS)
        assert task["max_steps"] >= 15
    assert prose.domain == "prose.com"


def test_shipped_task_text_never_names_rindler_tools(prose):
    for name in ("prose", "prose-hard"):
        site = sites.load_site(name)
        assert sites.task_text_leaks(site.tasks, site.mapping) == {}


def test_leak_check_finds_snake_case_tool_names_and_the_brand(prose):
    text = "First call view_accessories, then ask Rindler for the cart."
    assert sites.tool_name_leaks(text, prose.mapping) == ["view_accessories", "rindler"]
    # plain English that happens to match an action word is not a leak
    assert sites.tool_name_leaks("Go back to the accessories page and view the cart.", prose.mapping) == []
    # a longer identifier containing a tool name is not that tool name
    assert sites.tool_name_leaks("my_view_cart_notes", prose.mapping) == []


@pytest.mark.parametrize("text", ["Call Add_To_Cart for it.", "Then use ADD_TO_CART.", "add_to_cart"])
def test_leak_check_ignores_the_case_of_a_tool_name(prose, text):
    assert sites.tool_name_leaks(text, prose.mapping) == ["add_to_cart"]
    # the hyphenated English phrase is not the tool name
    assert sites.tool_name_leaks("Check the add-to-cart button.", prose.mapping) == []


def test_select_tasks_keeps_file_order_and_rejects_unknown_ids(prose):
    chosen = sites.select_tasks(prose.tasks, ["add-candle", "browse-accessories"])
    assert [t["id"] for t in chosen] == ["browse-accessories", "add-candle"]
    assert len(sites.select_tasks(prose.tasks, None)) == 10
    with pytest.raises(sites.SiteError, match="unknown task id"):
        sites.select_tasks(prose.tasks, ["nope"])


def test_select_tasks_refuses_an_empty_list_instead_of_choosing_every_task(prose):
    with pytest.raises(sites.SiteError, match="no task ids"):
        sites.select_tasks(prose.tasks, [])


def test_one_step_budget_for_both_arms(prose):
    task = {"id": "x", "max_steps": 20}
    assert sites.effective_max_steps(task) == 20
    assert sites.effective_max_steps(task, 8) == 8
    assert sites.effective_max_steps({"id": "y"}) == sites.DEFAULT_MAX_STEPS


def test_bad_site_names_and_missing_files_are_reported(tmp_path):
    with pytest.raises(sites.SiteError, match="bad site name"):
        sites.load_site("../server")
    with pytest.raises(sites.SiteError, match="no mapping file"):
        sites.load_site("nosuchsite")
    (tmp_path / "mappings").mkdir()
    (tmp_path / "instructions").mkdir()
    (tmp_path / "mappings" / "s.json").write_text('{"domain": "s.com", "screens": {}, "actions": {}}')
    with pytest.raises(sites.SiteError, match="invalid mapping"):
        sites.load_site("s", cli_dir=tmp_path)


def test_instruction_errors_name_the_task(tmp_path):
    (tmp_path / "instructions").mkdir()
    path = tmp_path / "instructions" / "s.yaml"
    path.write_text("tasks:\n  - id: a\n    name: A\n    goal: g\n    start_url: u\n")
    with pytest.raises(sites.SiteError, match="missing success_criteria"):
        sites.load_instructions("s", cli_dir=tmp_path)
    path.write_text(
        "tasks:\n"
        "  - {id: a, name: A, goal: g, start_url: u, success_criteria: c}\n"
        "  - {id: a, name: B, goal: g, start_url: u, success_criteria: c}\n"
    )
    with pytest.raises(sites.SiteError, match="duplicate task id"):
        sites.load_instructions("s", cli_dir=tmp_path)
    path.write_text("tasks:\n  - {id: a, name: A, goal: g, start_url: u, success_criteria: c, max_steps: 0}\n")
    with pytest.raises(sites.SiteError, match="max_steps"):
        sites.load_instructions("s", cli_dir=tmp_path)


def test_prose_hard_uses_the_same_mapping_as_prose():
    """prose-hard.json is a copy of prose.json (only the tasks differ), so a fix goes into both."""
    assert (sites.MAPPINGS_DIR / "prose.json").read_text() == (sites.MAPPINGS_DIR / "prose-hard.json").read_text()


def test_every_tool_has_a_description_written_for_this_site(prose):
    """The generic fallback ("Run the 'x' action of the ... mapping") says nothing to the model."""
    for tool in build_tools(prose.mapping):
        if tool["name"] in ("start_session", "close_session"):
            continue
        assert not tool["description"].startswith("Run the '"), tool["name"]
        for param in tool["inputSchema"].get("properties", {}).values():
            assert param.get("description")
