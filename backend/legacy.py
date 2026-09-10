"""Thin adapter to the unchanged scenario library, imported from the repo root.

Do not import the Streamlit entry point: its top-level code initializes the DB
and renders UI. Stateful routes use the shared application module.
"""
from scenario_library import (
    get_scenario_by_id,
    get_scenario_categories,
    get_scenarios_by_category,
)
from backend.schemas import ScenarioPreview


def scenario_categories() -> list[str]:
    return get_scenario_categories()


def scenario_previews(category: str | None = None) -> list[ScenarioPreview]:
    categories = [category] if category is not None else scenario_categories()
    return [
        ScenarioPreview.model_validate(scenario)
        for item in categories
        for scenario in get_scenarios_by_category(item)
    ]


def scenario_preview(scenario_id: str) -> ScenarioPreview | None:
    scenario = get_scenario_by_id(scenario_id)
    return ScenarioPreview.model_validate(scenario) if scenario is not None else None
