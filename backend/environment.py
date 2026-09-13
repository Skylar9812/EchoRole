"""Load optional local settings before importing application configuration."""
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ENV_PATH = Path(__file__).resolve().parents[1] / '.env'


def load_local_environment():
    # Explicit path prevents CWD-dependent discovery; OS values always win.
    # Literal values avoid expanding credentials containing ${...}.
    return load_dotenv(PROJECT_ENV_PATH, override=False, interpolate=False, encoding='utf-8-sig')
