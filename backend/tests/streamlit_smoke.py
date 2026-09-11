"""Offline Streamlit active-session compatibility check on a disposable database."""
import os
from pathlib import Path
import tempfile


def run():
    with tempfile.TemporaryDirectory() as temp:
        os.environ['ECHOROLE_DB_PATH'] = str(Path(temp) / 'streamlit.db')
        os.environ['ECHOROLE_AI_PROVIDER'] = 'local'
        from streamlit.testing.v1 import AppTest
        import application as app
        import interaction_service as service
        import database as db
        at = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'app.py'), default_timeout=30).run()
        assert not at.exception, at.exception
        at.text_input[0].set_value('Streamlit Alice')
        at.button(key='welcome_create_room').click().run()
        assert not at.exception, at.exception
        rid, uid = at.session_state.room_id, at.session_state.user_id
        bob = app.create_profile('Streamlit Bob')
        app.join_room(rid, bob['user_id'], 'Streamlit Bob')
        at.button(key='waiting_create_scenario_session').click().run()
        assert not at.exception, at.exception
        sid = db.get_session_by_room(rid)['id']
        assert db.get_user_role(sid, uid) == 'role_a'
        assert db.get_user_role(sid, bob['user_id']) == 'role_b'
        def input_label(items, label):
            return next(item for item in items if item.label == label)
        input_label(at.text_input, 'Message to the other user').set_value('Shared hello')
        input_label(at.button, 'Send Message').click().run()
        assert not at.exception, at.exception
        assert service.shared_messages(rid, uid)[0]['content'] == 'Shared hello'
        input_label(at.text_area, 'Reply to AI').set_value('I feel worried about how to explain my priorities.')
        input_label(at.button, 'Send to AI').click().run()
        assert not at.exception, at.exception
        assert len(service.coach_messages(sid, uid)) == 2
        assert service.coach_messages(sid, bob['user_id']) == []
        input_label(at.text_area, 'What action do you want to take next?').set_value('I will ask if we can sit down tonight and discuss our plans.')
        input_label(at.button, 'Submit Action and Advance Turn').click().run()
        assert not at.exception, at.exception
        assert service.turn_status(sid, uid)['state'] == 'waiting_for_other'
        result = service.submit_action(sid, bob['user_id'], 1, 'I will agree to sit down tonight and explain my concerns calmly.')
        assert result['state'] == 'advanced', result
        at.run()
        assert not at.exception, at.exception
        assert db.get_session_by_room(rid)['current_turn'] == 2
        assert len(service.progression(sid, uid)) == 1
        assert service.suggestion(sid, uid)['text']
        assert service.private_state(sid, uid)['brief_history']
        service.submit_action(sid, uid, 2, 'I will listen closely and ask what practical steps would help us move forward.')
        service.submit_action(sid, bob['user_id'], 2, 'I will explain my priorities and suggest that we agree on a realistic plan together.')
        at.run()
        assert not at.exception, at.exception
        input_label(at.select_slider, 'Rating').set_value(4.5)
        input_label(at.text_area, 'Private comment').set_value('Streamlit private feedback')
        input_label(at.button, 'Submit Feedback').click().run()
        assert not at.exception, at.exception
        assert app.peer_score(bob['user_id'])['total_points'] == 45
        assert app.peer_feedback_state(sid, uid)['feedback']['comment'] == 'Streamlit private feedback'
        print('PASS: Streamlit welcome, room, scenario, shared chat, private Coach, action waiting, joint advancement, evolved brief/suggestion and active rerender; turn-3 peer feedback and 45-point scoring')


if __name__ == '__main__':
    run()
