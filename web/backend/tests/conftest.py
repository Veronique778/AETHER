"""Shared test setup (AETHER 1.4).

Servers started by tests use a fixed session token so the existing functional
tests exercise the authenticated path. tests/test_security.py checks that
requests WITHOUT the token are refused, using http.client (no opener).
"""
import os
import urllib.request

TEST_TOKEN = 'aether-test-token'
os.environ.setdefault('AETHER_SESSION_TOKEN', TEST_TOKEN)
# Keep the suite offline and deterministic: never reach osdr.nasa.gov from tests.
os.environ.pop('AETHER_OSDR_TEST_MIRROR', None)


class _TokenHandler(urllib.request.BaseHandler):
    handler_order = 100

    def http_request(self, request):
        if request.host.startswith(('127.0.0.1', 'localhost')) and not request.has_header('X-aether-token'):
            request.add_header('X-AETHER-Token', os.environ['AETHER_SESSION_TOKEN'])
        return request


urllib.request.install_opener(urllib.request.build_opener(_TokenHandler()))

# The unchanged 1.4 cases exercise explicitly isolated, local demo compatibility.
# 1.5 tests use personal authentication with demo mode disabled.
import pytest

@pytest.fixture(autouse=True, scope='module')
def _select_api_generation(request):
    # Module fixtures can issue requests before function-scoped fixtures run.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('AETHER_LEGACY_DEMO', '0' if request.node.path.stem.endswith('_15') else '1')
        yield
