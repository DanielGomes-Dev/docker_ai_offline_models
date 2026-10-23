import asyncio
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Carga do pipeline (_load_pipe) com torch/diffusers falsos em sys.modules:
# nenhum peso é baixado, nada toca a GPU.
# ---------------------------------------------------------------------------


class _LoadedPipe(_FakePipe):
    def __init__(self):
        super().__init__()
        self.placement = []

    def to(self, device):
        self.placement.append(("to", device))
        return self

    def enable_model_cpu_offload(self):
        self.placement.append(("model_cpu_offload",))

    def enable_sequential_cpu_offload(self):
        self.placement.append(("sequential_cpu_offload",))


class _FakeGenerator:
    def __init__(self, device):
        self.device = device
        self.seed = None

    def manual_seed(self, seed):
        self.seed = seed
        return self


def _fake_libs():
    loads = []

    class FakeZImagePipeline:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            pipe = _LoadedPipe()
            loads.append({"model_id": model_id, "kwargs": kwargs, "pipe": pipe})
            return pipe

    class FakeQuantConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    torch = types.SimpleNamespace(
        bfloat16="torch.bfloat16", float16="torch.float16", Generator=_FakeGenerator
    )
    diffusers = types.SimpleNamespace(
        ZImagePipeline=FakeZImagePipeline, PipelineQuantizationConfig=FakeQuantConfig
    )
    return {"torch": torch, "diffusers": diffusers}, loads


class TestZImagePipelineLoading(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        modules, self.loads = _fake_libs()
        p = patch.dict(sys.modules, modules)
        p.start()
        self.addCleanup(p.stop)

    async def test_should_not_load_the_model_when_constructed(self):
        ZImageProvider({})
        self.assertEqual(self.loads, [])

    async def test_should_load_the_pipeline_once_and_reuse_it(self):
        prov = ZImageProvider({"offload": "none"})
        await prov.generate("a")
        await prov.generate("b")
        self.assertEqual(len(self.loads), 1)
        self.assertEqual(len(self.loads[0]["pipe"].calls), 2)

    async def test_should_quantize_transformer_and_text_encoder_to_nf4_by_default(self):
        await ZImageProvider({"offload": "none"}).generate("x")
        load = self.loads[0]
        self.assertEqual(load["model_id"], "Tongyi-MAI/Z-Image-Turbo")
        self.assertEqual(load["kwargs"]["torch_dtype"], "torch.bfloat16")
        quant = load["kwargs"]["quantization_config"].kwargs
        self.assertEqual(quant["quant_backend"], "bitsandbytes_4bit")
        self.assertEqual(quant["components_to_quantize"], ["transformer", "text_encoder"])
        self.assertEqual(
            quant["quant_kwargs"],
            {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_compute_dtype": "torch.bfloat16",
            },
        )

    async def test_versioned_config_puts_the_quantized_pipe_entirely_on_the_gpu(self):
        await ZImageProvider({"quantize": True, "offload": "none"}).generate("x")
        self.assertEqual(self.loads[0]["pipe"].placement, [("to", "cuda")])

    async def test_quantized_pipe_with_any_other_offload_uses_model_cpu_offload(self):
        for offload in ("model", "sequential"):
            modules, loads = _fake_libs()
            with patch.dict(sys.modules, modules):
                await ZImageProvider({"offload": offload}).generate("x")
            self.assertEqual(loads[0]["pipe"].placement, [("model_cpu_offload",)], offload)

    async def test_code_default_without_config_is_quantized_with_cpu_offload(self):
        # Ver DIV no relatório: a doc diz que cpu offload + 4-bit não é viável.
        await ZImageProvider().generate("x")
        self.assertIn("quantization_config", self.loads[0]["kwargs"])
        self.assertEqual(self.loads[0]["pipe"].placement, [("model_cpu_offload",)])

    async def test_full_precision_honours_each_offload_mode(self):
        expected = {
            "sequential": [("sequential_cpu_offload",)],
            "model": [("model_cpu_offload",)],
            "none": [("to", "cuda")],
        }
        for offload, placement in expected.items():
            modules, loads = _fake_libs()
            with patch.dict(sys.modules, modules):
                await ZImageProvider({"quantize": False, "offload": offload}).generate("x")
            self.assertNotIn("quantization_config", loads[0]["kwargs"])
            self.assertEqual(loads[0]["pipe"].placement, placement, offload)

    async def test_should_use_the_configured_dtype_and_fall_back_to_bfloat16(self):
        await ZImageProvider({"dtype": "float16", "offload": "none"}).generate("x")
        modules, loads = _fake_libs()
        with patch.dict(sys.modules, modules):
            await ZImageProvider({"dtype": "nao-existe", "offload": "none"}).generate("x")
        self.assertEqual(self.loads[0]["kwargs"]["torch_dtype"], "torch.float16")
        self.assertEqual(loads[0]["kwargs"]["torch_dtype"], "torch.bfloat16")

    async def test_seed_creates_a_cuda_generator_when_the_pipe_is_on_the_gpu(self):
        await ZImageProvider({"offload": "none"}).generate("x", seed=7)
        generator = self.loads[0]["pipe"].calls[0]["generator"]
        self.assertEqual((generator.device, generator.seed), ("cuda", 7))

    async def test_seed_creates_a_cpu_generator_when_offloading(self):
        await ZImageProvider({"offload": "model"}).generate("x", seed=3)
        generator = self.loads[0]["pipe"].calls[0]["generator"]
        self.assertEqual((generator.device, generator.seed), ("cpu", 3))

    async def test_seed_zero_still_creates_a_generator(self):
        await ZImageProvider({"offload": "none"}).generate("x", seed=0)
        self.assertEqual(self.loads[0]["pipe"].calls[0]["generator"].seed, 0)

    async def test_load_failure_propagates_and_next_call_tries_again(self):
        prov = ZImageProvider({"offload": "none"})
        with patch.object(
            sys.modules["diffusers"].ZImagePipeline,
            "from_pretrained",
            side_effect=OSError("sem rede"),
        ):
            with self.assertRaises(OSError):
                await prov.generate("x")
        self.assertIsNone(prov._pipe)
        await prov.generate("x")
        self.assertEqual(len(self.loads), 1)


class TestZImagePromptAndSize(unittest.IsolatedAsyncioTestCase):
    async def test_should_map_portrait_and_square(self):
        for aspect, size in (
            ("IMAGE_ASPECT_RATIO_PORTRAIT", (768, 1344)),
            ("IMAGE_ASPECT_RATIO_SQUARE", (1024, 1024)),
        ):
            prov, pipe = _provider()
            await prov.generate("x", aspect_ratio=aspect)
            self.assertEqual((pipe.calls[0]["width"], pipe.calls[0]["height"]), size)

    async def test_missing_aspect_ratio_uses_the_configured_default_size(self):
        prov, pipe = _provider(default_size=[512, 512])
        await prov.generate("x")
        self.assertEqual((pipe.calls[0]["width"], pipe.calls[0]["height"]), (512, 512))

    async def test_steps_and_guidance_come_from_the_config(self):
        prov, pipe = _provider(steps="4", guidance_scale="1.5")
        await prov.generate("x")
        self.assertEqual(pipe.calls[0]["num_inference_steps"], 4)
        self.assertEqual(pipe.calls[0]["guidance_scale"], 1.5)

    async def test_prompt_without_style_is_stripped(self):
        prov, pipe = _provider()
        await prov.generate("  um gato  ")
        self.assertEqual(pipe.calls[0]["prompt"], "um gato")

    async def test_dots_and_spaces_at_the_edges_of_prompt_plus_style_are_removed(self):
        prov, pipe = _provider()
        await prov.generate(" um gato", style="4k.")
        self.assertEqual(pipe.calls[0]["prompt"], "um gato. 4k")

    async def test_empty_style_is_ignored(self):
        prov, pipe = _provider()
        await prov.generate("um gato", style="")
        self.assertEqual(pipe.calls[0]["prompt"], "um gato")

    async def test_empty_prompt_does_not_load_the_pipeline(self):
        loaded = []
        prov = ZImageProvider({}, pipeline_factory=lambda: loaded.append(1) or _FakePipe())
        with self.assertRaisesRegex(ValueError, "Prompt vazio"):
            await prov.generate("")
        self.assertEqual(loaded, [])


class TestZImageGpuLock(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_generations_run_one_at_a_time_and_load_once(self):
        state = {"running": 0, "max_running": 0, "loads": 0}
        guard = threading.Lock()

        class _SlowPipe(_FakePipe):
            def __call__(self, **kwargs):
                with guard:
                    state["running"] += 1
                    state["max_running"] = max(state["max_running"], state["running"])
                time.sleep(0.05)
                with guard:
                    state["running"] -= 1
                return super().__call__(**kwargs)

        def factory():
            state["loads"] += 1
            time.sleep(0.05)  # janela de corrida na carga lazy
            return _SlowPipe()

        prov = ZImageProvider({}, pipeline_factory=factory)
        await asyncio.gather(*(prov.generate(f"p{i}") for i in range(4)))

        self.assertEqual(state["max_running"], 1)
        self.assertEqual(state["loads"], 1)


if __name__ == "__main__":
    unittest.main()
