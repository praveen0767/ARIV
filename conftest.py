import sys
import os
import httpx as _httpx

# Ensure the project root is in the Python path for imports during tests
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Compatibility wrapper for AsyncClient to accept 'app' argument in older httpx versions
class AsyncClient(_httpx.AsyncClient):
    """Wrapper around httpx.AsyncClient to support the ``app`` keyword used in tests.

    If ``app`` is provided, an ``ASGITransport`` is created so that the client can make
    requests against the supplied ASGI application. All other arguments are passed
    through to the original ``httpx.AsyncClient``.
    """

    def __init__(self, *args, **kwargs):
        app = kwargs.pop("app", None)
        if app is not None:
            transport = _httpx.ASGITransport(app=app)
            kwargs["transport"] = transport
            kwargs.setdefault("base_url", "http://test")
        super().__init__(*args, **kwargs)

# Expose the patched AsyncClient in the httpx module namespace for imports
_httpx.AsyncClient = AsyncClient

# Optionally, expose other names as before
from httpx import *  # noqa: F403,F401
