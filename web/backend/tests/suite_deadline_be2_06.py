"""Optional Linux/macOS full-suite watchdog; timeout is a FAILURE, never a skip.

Invoke explicitly: python -m pytest -p tests.suite_deadline_be2_06 ...
This runner guard does not replace storage, dispatch, auth, algorithms or BLE.
"""
import signal
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if not hasattr(signal,'SIGALRM'):
        yield
        return
    def expired(*_):
        pytest.fail('Full-suite watchdog: test exceeded 60 seconds (not passed)')
    old=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,60)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,old)
