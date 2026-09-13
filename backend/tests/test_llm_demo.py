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
