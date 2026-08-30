from abc import ABC, abstractmethod


class RouteRegisterInterface(ABC):

    @abstractmethod
    def execute(self, prefix: str, route: str, method: str, callback):
        """Registra uma rota no framework correspondente."""
        pass
