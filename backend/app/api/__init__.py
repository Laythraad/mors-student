"""API package — HTTP layer only.

Routes validate input, call exactly one service function and shape the
response. No business logic lives here, which is what lets the same service
be reused by the seed script, the tests and (later) a background worker.
"""

from .router import api_router

__all__ = ["api_router"]
