from src.interfaces.http.media.media_routes import MediaRoutes
from src.interfaces.http.route_register_fast_api import RouteRegisterFastApi


class Routes:
    def __init__(self):
        self.router_register = RouteRegisterFastApi()
        self.media_routes = MediaRoutes(routes_register=self.router_register)
        self.router = None

    def execute(self):
        self.media_routes.register()
        self.router = self.router_register.router
