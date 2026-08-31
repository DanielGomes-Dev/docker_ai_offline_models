"""Provedor de imagem via **Z-Image Turbo** (Tongyi-MAI/Z-Image-Turbo) rodando
local na GPU com `diffusers`.

- 6B params, licença Apache-2.0, afinado para realismo.
- Turbo/destilado: ~9 steps, `guidance_scale=0.0` (obrigatório para os Turbo).
- `torch` / `diffusers` são importados só na 1ª geração (lazy) — o módulo carrega
  sem GPU/torch (testes injetam `pipeline_factory`).
- A pipeline é bloqueante → `generate()` roda em `asyncio.to_thread`.
- Coexiste com o faster-whisper na mesma GPU via `enable_model_cpu_offload()`
  (offload="model", default) — pico de VRAM baixo, um pouco mais lento.
"""

from __future__ import annotations

import asyncio
import io

from src.domain.ports.image_provider import ImageProvider, ImageResult

_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"

# aspect_ratio (enum que o video_orchestrator manda) -> (width, height), múltiplos de 64
_SIZE_BY_ASPECT = {
    "IMAGE_ASPECT_RATIO_PORTRAIT": (768, 1344),
    "IMAGE_ASPECT_RATIO_LANDSCAPE": (1344, 768),
    "IMAGE_ASPECT_RATIO_SQUARE": (1024, 1024),
}
_DEFAULT_SIZE = (768, 1344)


class ZImageProvider(ImageProvider):
    name = "z_image"

    def __init__(self, config: dict | None = None, *, pipeline_factory=None):
        config = config or {}
        self.model_id = config.get("model_id", _MODEL_ID)
        self.dtype = config.get("dtype", "bfloat16")
        self.offload = config.get("offload", "model")  # "model" | "sequential" | "none"
        self.steps = int(config.get("steps", 9))
        self.guidance_scale = float(config.get("guidance_scale", 0.0))
        self.default_size = tuple(config.get("default_size", _DEFAULT_SIZE))
        self._pipeline_factory = pipeline_factory
        self._pipe = None

    # ------------------------------------------------------------------
    def _load_pipe(self):
        if self._pipe is not None:
            return self._pipe

        if self._pipeline_factory is not None:
            self._pipe = self._pipeline_factory()
            return self._pipe

        import torch  # lazy
        from diffusers import ZImagePipeline  # lazy

        dtype = getattr(torch, self.dtype, torch.bfloat16)
        pipe = ZImagePipeline.from_pretrained(self.model_id, torch_dtype=dtype)

        if self.offload == "sequential":
            pipe.enable_sequential_cpu_offload()
        elif self.offload == "model":
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        self._pipe = pipe
        return self._pipe

    def _run(self, full_prompt: str, width: int, height: int, seed: int | None) -> bytes:
        pipe = self._load_pipe()

        generator = None
        if seed is not None:
            import torch  # lazy

            device = "cuda" if self.offload == "none" else "cpu"
            generator = torch.Generator(device).manual_seed(int(seed))

        result = pipe(
            prompt=full_prompt,
            width=width,
            height=height,
            num_inference_steps=self.steps,
            guidance_scale=self.guidance_scale,
            generator=generator,
        )
        image = result.images[0]
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    # ------------------------------------------------------------------
    async def generate(
        self,
        prompt: str,
        *,
        style: str | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
    ) -> ImageResult:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt vazio para geração de imagem.")

        full_prompt = f"{prompt}. {style}".strip(". ").strip() if style else prompt.strip()
        width, height = _SIZE_BY_ASPECT.get(aspect_ratio or "", self.default_size)

        png = await asyncio.to_thread(self._run, full_prompt, width, height, seed)
        return ImageResult(image=png, mime="image/png")
