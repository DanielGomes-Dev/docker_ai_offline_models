import unittest
from unittest.mock import AsyncMock

from src.application.services.media.image.image_service import ImageService
from src.domain.ports.image_provider import ImageProvider, ImageResult


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


if __name__ == "__main__":
    unittest.main()
