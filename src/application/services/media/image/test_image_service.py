import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.application.services.media.image import image_service as image_module

from src.application.services.media.image.image_service import ImageService
from src.domain.ports.image_provider import ImageProvider, ImageResult
from src.infra.external.z_image.z_image_provider import ZImageProvider


class _FakeProvider(ImageProvider):
    name = "fake"

    def __init__(self):
        self.mock = AsyncMock(return_value=ImageResult(b"pngbytes", "image/png"))

    async def generate(self, prompt, *, style=None, aspect_ratio=None, seed=None):
        return await self.mock(prompt, style=style, aspect_ratio=aspect_ratio, seed=seed)


class TestImageService(unittest.IsolatedAsyncioTestCase):
    async def test_should_delegate_to_the_injected_provider(self):
        provider = _FakeProvider()
        service = ImageService(provider=provider)

        result = await service.generate(
            "um gato", style="anime", aspect_ratio="P", seed=7
        )

        self.assertEqual(result.image, b"pngbytes")
        provider.mock.assert_awaited_once_with(
            "um gato", style="anime", aspect_ratio="P", seed=7
        )

    def test_should_default_to_z_image_from_config(self):
        service = ImageService(config={"provider": "z_image", "z_image": {}})
        self.assertEqual(service.provider.name, "z_image")

    def test_should_raise_on_unknown_provider(self):
        with self.assertRaises(ValueError):
            ImageService(config={"provider": "nope"})


class TestImageServiceProviderSelection(unittest.TestCase):
    """Seleção do provider pelo `config.json` (hoje só `z_image`)."""

    def _with_config_file(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        p = patch.object(image_module, "_CONFIG_PATH", path)
        p.start()
        self.addCleanup(p.stop)

    def test_should_build_z_image_from_the_versioned_config_json(self):
        provider = ImageService().provider
        self.assertIsInstance(provider, ZImageProvider)
        self.assertEqual(provider.model_id, "Tongyi-MAI/Z-Image-Turbo")
        self.assertTrue(provider.quantize)
        self.assertEqual(provider.offload, "none")
        self.assertEqual((provider.steps, provider.guidance_scale), (9, 0.0))
        self.assertEqual(provider.default_size, (768, 1344))

    def test_should_not_load_the_pipeline_when_building_the_service(self):
        # carga do modelo é lazy: só na 1ª geração
        self.assertIsNone(ImageService().provider._pipe)

    def test_should_fall_back_to_z_image_when_the_config_file_is_missing(self):
        self._with_config_file(None)
        service = ImageService()
        self.assertEqual(service.config, {"provider": "z_image"})
        self.assertIsInstance(service.provider, ZImageProvider)

    def test_should_fall_back_to_z_image_when_the_config_file_is_invalid_json(self):
        self._with_config_file("nao e json")
        self.assertIsInstance(ImageService().provider, ZImageProvider)

    def test_provider_without_config_section_keeps_the_pipe_on_the_gpu(self):
        # DIV-3: sem a seção `z_image` (config ausente/inválido), o default do
        # código é offload="none" -- o mesmo do config.json versionado.
        provider = ImageService(config={"provider": "z_image"}).provider
        self.assertTrue(provider.quantize)
        self.assertEqual(provider.offload, "none")

    def test_missing_config_file_falls_back_to_the_safe_offload(self):
        self._with_config_file(None)
        self.assertEqual(ImageService().provider.offload, "none")

    def test_should_read_the_config_file_when_given_an_empty_dict(self):
        self._with_config_file(json.dumps({"provider": "z_image", "z_image": {"steps": 4}}))
        self.assertEqual(ImageService(config={}).provider.steps, 4)

    def test_should_name_the_unknown_provider_in_the_error(self):
        with self.assertRaisesRegex(ValueError, "Provider de imagem desconhecido: 'sdxl'"):
            ImageService(config={"provider": "sdxl"})


if __name__ == "__main__":
    unittest.main()
