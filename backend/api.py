from typing import Literal
from fastapi import APIRouter, HTTPException, Depends, Request
import application as services
from backend.identity import current_user, issue_identity, issue_enrollment, enrollment_user
from backend.schemas import ProfileCreate, ProfileResponse, RoomResponse, MemberResponse, SessionCreate, SessionResponse
from backend.authorization import room_member
from backend.schemas import ProfileState, RoomCreate, JoinCode, EnrollmentResponse, PeerScore, PeerFeedbackState, PeerFeedbackSend
from backend import legacy
from backend.schemas import HealthResponse, ScenarioPreview

router = APIRouter()


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
def create_profile(body: ProfileCreate, request: Request):
    profile = services.enroll_profile(enrollment_user(request), **body.model_dump())
    return {**profile, "access_token": issue_identity(request, profile["user_id"])}


@router.get("/me", response_model=ProfileState)
def me(user_id: str = Depends(current_user)):
    return services.get_user_profile(user_id)


@router.post("/rooms", response_model=RoomResponse, status_code=201)
def create_room(body: RoomCreate | None = None, user_id: str = Depends(current_user)):
    return services.create_room_retry_safe(user_id, body.request_id if body else None, body.language if body else "en")


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
def scenarios(category: str | None = None, language: Literal["en", "zh-CN", "zh-TW"] = "en") -> list[ScenarioPreview]:
    """Public previews, optionally filtered by exact legacy category. Unknown category: []."""
    return legacy.scenario_previews(category, language)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioPreview, tags=["scenarios"])
def scenario(scenario_id: str) -> ScenarioPreview:
    result = legacy.scenario_preview(scenario_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return result

@router.post('/rooms/join', response_model=RoomResponse)
def join_code(body: JoinCode, user_id: str = Depends(current_user)):
    return services.join_by_code(body.invite_code, user_id)


@router.post('/rooms/{room_id}/leave')
def leave(room_id: int, user_id: str = Depends(current_user)):
    return services.leave_room(room_id, user_id)


@router.post('/me', response_model=ProfileState)
def update_me(body: ProfileCreate, user_id: str = Depends(current_user)):
    return services.update_profile(user_id, **body.model_dump())


@router.post('/profiles/prepare', response_model=EnrollmentResponse)
def prepare_profile(request: Request):
    return {'enrollment_token': issue_enrollment(request)}


@router.get('/me/score', response_model=PeerScore)
def my_score(user_id: str = Depends(current_user)):
    return services.peer_score(user_id)


@router.get('/sessions/{session_id}/peer-feedback', response_model=PeerFeedbackState)
def peer_feedback(session_id: int, user_id: str = Depends(current_user)):
    return services.peer_feedback_state(session_id, user_id)


@router.post('/sessions/{session_id}/peer-feedback', response_model=PeerFeedbackState)
def submit_feedback(session_id: int, body: PeerFeedbackSend, user_id: str = Depends(current_user)):
    return services.submit_peer_feedback(session_id, user_id, **body.model_dump())
