import unittest

from src.infra.external.z_image.z_image_provider import ZImageProvider


class _FakeImage:
    def save(self, buf, format="PNG"):  # noqa: A002 - assinatura do PIL
        buf.write(b"\x89PNG\r\n\x1a\nFAKEDATA")


class _FakeResult:
    images = [_FakeImage()]


class _FakePipe:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResult()


def _provider(pipe=None, **config):
    pipe = pipe or _FakePipe()
    prov = ZImageProvider(config or {}, pipeline_factory=lambda: pipe)
    return prov, pipe


class TestZImageProvider(unittest.IsolatedAsyncioTestCase):
    async def test_should_return_png_bytes(self):
        prov, pipe = _provider()
        result = await prov.generate("um gato preto na floresta")
        self.assertEqual(result.mime, "image/png")
        self.assertTrue(result.image.startswith(b"\x89PNG"))
        self.assertEqual(len(pipe.calls), 1)
        self.assertEqual(pipe.calls[0]["prompt"], "um gato preto na floresta")

    async def test_should_append_style_to_the_prompt(self):
        prov, pipe = _provider()
        await prov.generate("um gato", style="cinematic, 4k")
        self.assertEqual(pipe.calls[0]["prompt"], "um gato. cinematic, 4k")

    async def test_should_map_the_aspect_ratio_to_a_size(self):
        prov, pipe = _provider()
        await prov.generate("x", aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE")
        self.assertEqual(pipe.calls[0]["width"], 1344)
        self.assertEqual(pipe.calls[0]["height"], 768)

    async def test_should_default_to_portrait_for_unknown_aspect_ratio(self):
        prov, pipe = _provider()
        await prov.generate("x", aspect_ratio="whatever")
        self.assertEqual(pipe.calls[0]["width"], 768)
        self.assertEqual(pipe.calls[0]["height"], 1344)

    async def test_should_use_turbo_defaults(self):
        prov, pipe = _provider()
        await prov.generate("x")
        self.assertEqual(pipe.calls[0]["num_inference_steps"], 9)
        self.assertEqual(pipe.calls[0]["guidance_scale"], 0.0)
        self.assertIsNone(pipe.calls[0]["generator"])

    async def test_should_raise_on_empty_prompt(self):
        prov, _ = _provider()
        with self.assertRaises(ValueError):
            await prov.generate("   ")


if __name__ == "__main__":
    unittest.main()
