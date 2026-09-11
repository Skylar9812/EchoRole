from fastapi import APIRouter, HTTPException, Depends, Request
import application as services
from backend.identity import current_user, issue_identity
from backend.schemas import ProfileCreate, ProfileResponse, RoomResponse, MemberResponse, SessionCreate, SessionResponse
from backend.authorization import room_member
from backend.schemas import ProfileState
from backend import legacy
from backend.schemas import HealthResponse, ScenarioPreview

router = APIRouter()


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
def create_profile(body: ProfileCreate, request: Request):
    profile = services.create_profile(**body.model_dump())
    return {**profile, "access_token": issue_identity(request, profile["user_id"])}


@router.get("/me", response_model=ProfileState)
def me(user_id: str = Depends(current_user)):
    return services.get_user_profile(user_id)


@router.post("/rooms", response_model=RoomResponse, status_code=201)
def create_room(user_id: str = Depends(current_user)):
    return services.create_room(user_id, services.get_user_profile(user_id)["display_name"])


@router.post("/rooms/{room_id}/join", response_model=RoomResponse)
def join_room(room_id: int, user_id: str = Depends(current_user)):
    return services.join_room(room_id, user_id, services.get_user_profile(user_id)["display_name"], activate=True)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
def room(room_id: int, user_id: str = Depends(room_member)):
    return services.room_state(room_id)


@router.get("/rooms/{room_id}/members", response_model=list[MemberResponse])
def members(room_id: int, user_id: str = Depends(room_member)):
    return services.list_members(room_id)


@router.post("/rooms/{room_id}/sessions", response_model=SessionResponse, status_code=201)
def create_session(room_id: int, body: SessionCreate, user_id: str = Depends(room_member)):
    return services.start_session(room_id, user_id, body.scenario_id, body.expected_session_id)


@router.get("/rooms/{room_id}/session", response_model=SessionResponse | None)
def session(room_id: int, user_id: str = Depends(room_member)):
    return services.public_session(room_id)


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
