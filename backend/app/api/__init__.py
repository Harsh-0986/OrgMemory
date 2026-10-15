"""HTTP layer: routers, dependencies and error handling."""

from app.api.deps import get_repository
from app.api.errors import register_exception_handlers

__all__ = ["get_repository", "register_exception_handlers"]