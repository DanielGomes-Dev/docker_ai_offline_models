from platform_core.http import RouteRegisterInterface
from src.interfaces.http.media.media_controller import MediaController


class MediaRoutes:
    def __init__(self, routes_register: RouteRegisterInterface):
        self.routes_register = routes_register
        self.controller = MediaController()

    def register(self):
        # texto -> áudio (edge-tts por padrão)
        self.routes_register.execute(
            prefix="", route="/tts", method="POST", callback=self.controller.tts
        )
        # áudio -> timestamps por palavra (faster-whisper)
        self.routes_register.execute(
            prefix="",
            route="/transcribe",
            method="POST_FILE",
            callback=self.controller.transcribe,
        )
        # texto -> imagem (Z-Image Turbo local, via diffusers)
        self.routes_register.execute(
            prefix="", route="/image", method="POST", callback=self.controller.image
        )
