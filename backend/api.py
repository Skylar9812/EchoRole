from fastapi import APIRouter, HTTPException
from backend import legacy
from backend.schemas import HealthResponse, ScenarioPreview

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Process liveness only; does not claim database or provider readiness."""
    return HealthResponse()


@router.get("/scenarios/categories", response_model=list[str], tags=["scenarios"])
def categories() -> list[str]:
    return legacy.scenario_categories()


@router.get("/scenarios", response_model=list[ScenarioPreview], tags=["scenarios"])
def scenarios(category: str | None = None) -> list[ScenarioPreview]:
    """Public previews, optionally filtered by exact legacy category. Unknown category: []."""
    return legacy.scenario_previews(category)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioPreview, tags=["scenarios"])
def scenario(scenario_id: str) -> ScenarioPreview:
    result = legacy.scenario_preview(scenario_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return result
