"""Offline real-provider safeguards; no external requests."""
import os
import unittest
from unittest.mock import patch
from application import ApplicationError
from provider_boundary import require_llm_configuration

class LLMDemoTests(unittest.TestCase):
    def test_missing_key_is_clear_configuration_error(self):
        with patch.dict(os.environ, {'ECHOROLE_AI_PROVIDER':'llm', 'ECHOROLE_LLM_API_KEY':'', 'DEEPSEEK_API_KEY':''}):
            with self.assertRaisesRegex(ApplicationError, 'ECHOROLE_LLM_API_KEY') as ctx:
                require_llm_configuration()
            self.assertEqual(ctx.exception.status_code, 503)

    def test_invalid_base_does_not_disclose_key(self):
        with patch.dict(os.environ, {'ECHOROLE_AI_PROVIDER':'llm', 'ECHOROLE_LLM_API_KEY':'test-secret', 'ECHOROLE_LLM_API_BASE':'file:///tmp/provider'}):
            with self.assertRaisesRegex(ApplicationError, 'ECHOROLE_LLM_API_BASE') as ctx:
                require_llm_configuration()
            self.assertNotIn('test-secret', str(ctx.exception))

    def test_local_mode_needs_no_key(self):
        with patch.dict(os.environ, {'ECHOROLE_AI_PROVIDER':'local'}):
            require_llm_configuration()

    def test_real_coach_missing_key_cannot_return_local_template(self):
        import ai_engine as ai
        config = ai.AIEngineConfig(provider_name='llm', provider_env_present=True, llm_api_key='')
        provider = ai.DeepSeekOpenAICompatibleProvider(ai.LocalDeterministicAIProvider(), config)
        with patch.object(ai, '_generate_dynamic_ai_feedback_local', return_value='LOCAL TEMPLATE'), patch.object(provider, '_perform_chat_completion_request') as request:
            with self.assertRaisesRegex(RuntimeError, 'fallback is disabled'):
                provider.generate_dynamic_ai_feedback('role_a', 'I am worried.', 1, 'A deadline approaches.')
            request.assert_not_called()


    def test_joint_scene_quality_is_language_aware(self):
        import ai_engine as ai
        cases = {
            'en': ('Next week at the meeting, the manager proposes a deadline, but the employee worries about workload.', 'The conversation moves forward.'),
            'zh-CN': ('第二天的团队会议上，主管提出新的截止日期，但员工担心工作量过大，双方需要决定如何调整计划。', '对话有了进展，双方的关系进入新的阶段。'),
            'zh-TW': ('第二天的團隊會議上，主管提出新的截止日期，但員工擔心工作量過大，雙方需要決定如何調整計畫。', '對話有了進展，雙方的關係進入新的階段。'),
        }
        for language, (concrete, abstract) in cases.items():
            with self.subTest(language=language):
                result = {'shared_situation': concrete}
                self.assertIs(ai._validate_joint_story_progression_result(result, language), result)
                with self.assertRaisesRegex(ValueError, 'Abstract shared_situation'):
                    ai._validate_joint_story_progression_result({'shared_situation': abstract}, language)
                with self.assertRaisesRegex(ValueError, 'Missing shared_situation'):
                    ai._validate_joint_story_progression_result({}, language)
        # A time anchor alone, or an emotional concern alone, is still insufficient.
        for language, scene, tension in [
            ('zh-CN', '第二天，他们一起喝咖啡。', '双方仍然担心彼此不理解。'),
            ('zh-TW', '第二天，他們一起喝咖啡。', '雙方仍然擔心彼此不理解。'),
        ]:
            for text in (scene, tension):
                with self.assertRaisesRegex(ValueError, 'Abstract shared_situation'):
                    ai._validate_joint_story_progression_result({'shared_situation': text}, language)

    def test_joint_provider_uses_room_language_on_first_and_retry_responses(self):
        import ai_engine as ai
        import json
        import io
        from contextlib import redirect_stdout
        from unittest.mock import Mock
        scenes = {
            'en': 'Next week at the meeting, the manager proposes a deadline, but the employee worries about workload.',
            'zh-CN': '第二天的团队会议上，主管提出新的截止日期，但员工担心工作量过大。',
            'zh-TW': '第二天的團隊會議上，主管提出新的截止日期，但員工擔心工作量過大。',
        }
        config = ai.AIEngineConfig(provider_name='llm', provider_env_present=True, llm_api_key='test-only')
        fallback = Mock()
        fallback.generate_next_situation_from_joint_actions.return_value = {'shared_situation': 'offline fixture'}
        provider = ai.DeepSeekOpenAICompatibleProvider(fallback, config)
        def response(scene):
            result = {key: 'Private test fixture' for key in ('role_a_perspective', 'role_b_perspective', 'next_decision_point', 'updated_role_a_brief', 'updated_role_b_brief', 'role_a_suggestion', 'role_b_suggestion')}
            result['shared_situation'] = scene
            return (200, json.dumps({'choices': [{'message': {'content': json.dumps(result)}}]}), 1.0)
        for language, scene in scenes.items():
            for retry in (False, True):
                with self.subTest(language=language, retry=retry), redirect_stdout(io.StringIO()), patch.object(ai, '_write_story_progression_prompt_debug_file'), patch.object(provider, '_perform_chat_completion_request') as request:
                    request.side_effect = ([response('Generic progress.')] if retry else []) + [response(scene)]
                    result = provider.generate_next_situation_from_joint_actions({'language': language, 'current_turn': 1}, 'Fictional action A', 'Fictional action B')
                    self.assertEqual(result['shared_situation'], scene)
                    self.assertEqual(request.call_count, 2 if retry else 1)
