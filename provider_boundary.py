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
