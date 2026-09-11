"""Thin authenticated boundaries; orchestration lives in interaction_service."""
from fastapi import APIRouter, Depends, Query
from backend.authorization import room_member, session_member, role_owner, SessionParticipant
from backend.interaction_schemas import (
    ChatSend, CoachSend, TurnRequest, ActionSend, Recovery, TurnRecovery,
    SharedMessage, PrivateState, CoachMessage, CoachResult, Suggestion, TurnStatus, ProgressionEntry,
)
import interaction_service as service

router = APIRouter()


@router.get('/rooms/{room_id}/messages', response_model=list[SharedMessage])
def messages(room_id: int, user_id: str = Depends(room_member)):
    return service.shared_messages(room_id, user_id)


@router.post('/rooms/{room_id}/messages', response_model=SharedMessage)
def send_message(room_id: int, body: ChatSend, user_id: str = Depends(room_member)):
    return service.send_chat(room_id, user_id, body.content, body.request_id)


@router.get('/sessions/{session_id}/private', response_model=PrivateState)
def private(p: SessionParticipant = Depends(session_member)):
    return service.private_state(p.session_id, p.user_id)


@router.get('/sessions/{session_id}/roles/{role_name}/private', response_model=PrivateState)
def private_role(p: SessionParticipant = Depends(role_owner)):
    return service.private_state(p.session_id, p.user_id)


@router.get('/sessions/{session_id}/coach/messages', response_model=list[CoachMessage])
def coach_messages(turn_index: int | None = Query(default=None, ge=1), p: SessionParticipant = Depends(session_member)):
    return service.coach_messages(p.session_id, p.user_id, turn_index)


@router.post('/sessions/{session_id}/coach/messages', response_model=CoachResult)
def send_coach(body: CoachSend, p: SessionParticipant = Depends(session_member)):
    return service.send_coach(p.session_id, p.user_id, body.turn_index, body.content, body.request_id)


@router.get('/sessions/{session_id}/coach/requests/{request_id}', response_model=CoachResult)
def coach_request(request_id: str, p: SessionParticipant = Depends(session_member)):
    return service.coach_request(p.session_id, p.user_id, request_id)


@router.post('/sessions/{session_id}/coach/requests/{request_id}/recover', response_model=CoachResult)
def recover_coach(request_id: str, body: Recovery, p: SessionParticipant = Depends(session_member)):
    return service.recover_coach(p.session_id, p.user_id, request_id, body.attempt_id, body.acknowledge_uncertain)


@router.get('/sessions/{session_id}/suggestion', response_model=Suggestion)
def suggestion(p: SessionParticipant = Depends(session_member)):
    return service.suggestion(p.session_id, p.user_id)


@router.get('/sessions/{session_id}/turn', response_model=TurnStatus)
@router.get('/sessions/{session_id}/turn/status', response_model=TurnStatus)
def turn_status(turn_index: int | None = Query(default=None, ge=1), p: SessionParticipant = Depends(session_member)):
    return service.turn_status(p.session_id, p.user_id, turn_index)


@router.post('/sessions/{session_id}/turn/actions', response_model=TurnStatus)
def action(body: ActionSend, p: SessionParticipant = Depends(session_member)):
    return service.submit_action(p.session_id, p.user_id, body.turn_index, body.action_text)


@router.post('/sessions/{session_id}/turn/complete', response_model=TurnStatus)
def complete(body: TurnRequest, p: SessionParticipant = Depends(session_member)):
    return service.advance_turn(p.session_id, p.user_id, body.turn_index)


@router.post('/sessions/{session_id}/turn/recover', response_model=TurnStatus)
def recover_turn(body: TurnRecovery, p: SessionParticipant = Depends(session_member)):
    return service.recover_turn(p.session_id, p.user_id, body.turn_index, body.attempt_id, body.acknowledge_uncertain)


@router.get('/sessions/{session_id}/progression', response_model=list[ProgressionEntry])
def progression(p: SessionParticipant = Depends(session_member)):
    return service.progression(p.session_id, p.user_id)


@router.get('/sessions/{session_id}/coach/requests', response_model=list[CoachResult])
def coach_requests(p: SessionParticipant = Depends(session_member)):
    return service.coach_requests(p.session_id, p.user_id)


@router.post('/sessions/{session_id}/coach/requests/{request_id}/complete', response_model=CoachResult)
def persist_coach(request_id: str, p: SessionParticipant = Depends(session_member)):
    return service.persist_coach_request(p.session_id, p.user_id, request_id)
