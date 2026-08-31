"""Provedor de imagem via **Z-Image Turbo** (Tongyi-MAI/Z-Image-Turbo) rodando
local na GPU com `diffusers`.

- 6B params, licença Apache-2.0, afinado para realismo.
- Turbo/destilado: ~9 steps, `guidance_scale=0.0` (obrigatório para os Turbo).
- `torch` / `diffusers` são importados só na 1ª geração (lazy) — o módulo carrega
  sem GPU/torch (testes injetam `pipeline_factory`).
- A pipeline é bloqueante → `generate()` roda em `asyncio.to_thread`.
- **Quantização 4-bit (bitsandbytes, default)**: o modelo full-precision (~30 GB
  entre DiT + text encoder Qwen + VAE) não cabe nos 15 GB de RAM da VM (OOM no
  `cpu_offload`). Em NF4 4-bit o transformer + text encoder ficam em ~9 GB e
  vão direto pra GPU (`pipe.to("cuda")`), coexistindo com o whisper (~2 GB) nos
  16 GB da RTX 5060 Ti. `quantize=false` no config volta pro caminho
  full-precision + `enable_model_cpu_offload()`.
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
        self.quantize = bool(config.get("quantize", True))
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

        if self.quantize:
            from diffusers import PipelineQuantizationConfig  # lazy

            quant = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_4bit",
                quant_kwargs={
                    "load_in_4bit": True,
                    "bnb_4bit_quant_type": "nf4",
                    "bnb_4bit_compute_dtype": dtype,
                },
                components_to_quantize=["transformer", "text_encoder"],
            )
            pipe = ZImagePipeline.from_pretrained(
                self.model_id, quantization_config=quant, torch_dtype=dtype
            )
            # cpu-offload mesmo em 4-bit: o whisper large-v3 fica residente na
            # mesma GPU (~2-3 GB), e 4-bit inteiro na VRAM + ativações estoura os
            # 16 GB. Com offload, só o componente ativo sobe pra GPU (pico ~5-6 GB).
            if self.offload == "none":
                pipe.to("cuda")
            else:
                pipe.enable_model_cpu_offload()
        else:
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

            # CPU generator é sempre seguro (com offload os módulos migram de device).
            on_gpu = self.offload == "none"
            generator = torch.Generator("cuda" if on_gpu else "cpu").manual_seed(int(seed))

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
