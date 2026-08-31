"""Application factory. Importing this module has no side effect until create_app() runs."""

from platform_core.http import create_app as _base

from src.config import settings
from src.interfaces.http.routes import Routes


def create_app():
    routes = Routes()
    routes.execute()
    return _base(
        title=settings.app_title,
        description=settings.app_description,
        version=settings.app_version,
        routers=[routes.router],
    )
