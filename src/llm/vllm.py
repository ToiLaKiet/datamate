"""Offline chat inference with vLLM on NVIDIA GPUs."""

from collections.abc import Mapping, Sequence

from .base import BaseLLM


class VLLMLLM(BaseLLM):
    """Load a vLLM-compatible model once and reuse it for each chat call."""

    def __init__(
        self,
        model_id: str,
        *,
        max_model_len: int = 16384,
        gpu_memory_utilization: float = 0.85,
        tensor_parallel_size: int = 1,
        quantization: str | None = None,
    ) -> None:
        if not model_id:
            raise ValueError("model_id must not be empty")
        if max_model_len < 1:
            raise ValueError("max_model_len must be positive")
        if not 0 < gpu_memory_utilization <= 1:
            raise ValueError("gpu_memory_utilization must be in (0, 1]")
        if tensor_parallel_size < 1:
            raise ValueError("tensor_parallel_size must be positive")

        try:
            from vllm import LLM, SamplingParams
        except ImportError as exc:
            raise RuntimeError(
                "vLLM is unavailable; on NVIDIA Linux install the CUDA group "
                "with `uv sync --group cuda`"
            ) from exc

        self.model_id = model_id
        self._sampling_params = SamplingParams
        self._llm = LLM(
            model=model_id,
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            tensor_parallel_size=tensor_parallel_size,
            dtype="auto",
            quantization=quantization,
        )

    def infer(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        """Apply the model's chat template and return one generated response."""
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature < 0:
            raise ValueError("temperature must not be negative")

        outputs = self._llm.chat(
            [[dict(message) for message in messages]],
            sampling_params=self._sampling_params(
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            use_tqdm=False,
        )
        return outputs[0].outputs[0].text
