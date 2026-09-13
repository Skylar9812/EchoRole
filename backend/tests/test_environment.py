"""Local dotenv startup checks using disposable, synthetic credentials only."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from backend import environment
from provider_boundary import require_llm_configuration
from application import ApplicationError

class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '.env'
        self.path.write_text('ECHOROLE_AI_PROVIDER=llm\nECHOROLE_LLM_API_KEY=synthetic-test-only\nECHOROLE_LLM_API_BASE=https://example.invalid\nECHOROLE_LLM_MODEL=test-model\n')

    def test_explicit_project_path(self):
        self.assertEqual(environment.PROJECT_ENV_PATH, Path(__file__).resolve().parents[2] / '.env')

    def test_load_selects_llm_without_logging_credentials(self):
        from ai_engine import AIEngineConfig
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(environment, 'PROJECT_ENV_PATH', self.path), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertTrue(environment.load_local_environment())
            require_llm_configuration()
            config = AIEngineConfig.from_env()
            self.assertEqual(config.resolved_provider_name(), 'llm')
            self.assertTrue(config.has_llm_api_key())
        self.assertEqual(output.getvalue(), '')

    def test_shell_values_win(self):
        values = {'ECHOROLE_AI_PROVIDER':'local','ECHOROLE_LLM_API_KEY':'shell-test-only','ECHOROLE_LLM_API_BASE':'https://shell.invalid','ECHOROLE_LLM_MODEL':'shell-model'}
        with patch.dict(os.environ, values, clear=True), patch.object(environment, 'PROJECT_ENV_PATH', self.path):
            environment.load_local_environment()
            for name, value in values.items():
                self.assertEqual(os.environ[name], value)

    def test_empty_shell_key_is_preserved_and_fails_clearly(self):
        with patch.dict(os.environ, {'ECHOROLE_LLM_API_KEY':''}, clear=True), patch.object(environment, 'PROJECT_ENV_PATH', self.path):
            environment.load_local_environment()
            with self.assertRaisesRegex(ApplicationError, 'ECHOROLE_LLM_API_KEY'):
                require_llm_configuration()

    def test_actual_fastapi_import_loads_before_application(self):
        code = "import backend.environment as e; from pathlib import Path; e.PROJECT_ENV_PATH=Path(__import__('sys').argv[1]); import backend.main; import os; assert os.environ['ECHOROLE_AI_PROVIDER']=='llm'; assert os.environ['ECHOROLE_LLM_MODEL']=='test-model'"
        env = {k:v for k,v in os.environ.items() if not k.startswith('ECHOROLE_') and k != 'DEEPSEEK_API_KEY'}
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, 'FastAPI import must load local environment')
        self.assertNotIn(b'synthetic-test-only', result.stdout + result.stderr)

    def test_missing_file_is_optional(self):
        with patch.object(environment, 'PROJECT_ENV_PATH', self.path.with_name('absent')):
            self.assertFalse(environment.load_local_environment())
