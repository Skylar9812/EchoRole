"""Request-local transport outcome observation, independent of provider debug globals."""
from contextlib import contextmanager
from contextvars import ContextVar

_observer = ContextVar('echorole_provider_outcome', default=None)


@contextmanager
def observe():
    outcome = {'uncertain': False}
    token = _observer.set(outcome)
    try:
        yield outcome
    finally:
        _observer.reset(token)


def mark_uncertain():
    outcome = _observer.get()
    if outcome is not None:
        outcome['uncertain'] = True


def require_llm_configuration():
    """Validate local configuration before claiming external work; never expose secrets."""
    import os
    from urllib.parse import urlsplit
    from application import ApplicationError
    key = (os.getenv('ECHOROLE_LLM_API_KEY') or os.getenv('DEEPSEEK_API_KEY') or '').strip()
    provider = (os.getenv('ECHOROLE_AI_PROVIDER') or ('llm' if key else 'local')).strip().lower()
    if provider != 'llm':
        return
    if not key:
        raise ApplicationError('LLM configuration missing: set ECHOROLE_LLM_API_KEY on the backend.', 503)
    base = urlsplit(os.getenv('ECHOROLE_LLM_API_BASE') or 'https://api.deepseek.com')
    if base.scheme not in ('http', 'https') or not base.hostname or base.username or base.password or base.query or base.fragment:
        raise ApplicationError('LLM configuration invalid: ECHOROLE_LLM_API_BASE must be an HTTP(S) provider base URL.', 503)
