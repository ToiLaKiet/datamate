"""Offline chat inference with vLLM on NVIDIA GPUs."""

from collections.abc import Mapping, Sequence
from typing import Any

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
        tokenizer_id: str | None = None,
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
        self._reasoning_enabled = "deepseek-r1" in model_id.casefold()
        options = {
            "model": model_id,
            "max_model_len": max_model_len,
            "gpu_memory_utilization": gpu_memory_utilization,
            "tensor_parallel_size": tensor_parallel_size,
            "dtype": "auto",
            "quantization": quantization,
        }
        if tokenizer_id is not None:
            options["tokenizer"] = tokenizer_id
        if self._reasoning_enabled:
            from vllm.config import ReasoningConfig

            options["reasoning_config"] = ReasoningConfig(
                reasoning_start_str="<think>", reasoning_end_str="</think>"
            )
        self._llm = LLM(**options)

    def infer(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        output_schema: dict[str, Any] | None = None,
        thinking_token_budget: int | None = None,
    ) -> str:
        """Apply the model's chat template and return one generated response."""
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature < 0:
            raise ValueError("temperature must not be negative")
        if thinking_token_budget is not None and thinking_token_budget < 1:
            raise ValueError("thinking_token_budget must be positive")

        sampling_options: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}
        if output_schema is not None:
            from vllm.sampling_params import StructuredOutputsParams

            sampling_options["structured_outputs"] = StructuredOutputsParams(json=output_schema)
        if self._reasoning_enabled and thinking_token_budget is not None:
            sampling_options["thinking_token_budget"] = thinking_token_budget

        outputs = self._llm.chat(
            [[dict(message) for message in messages]],
            sampling_params=self._sampling_params(**sampling_options),
            use_tqdm=False,
        )
        return outputs[0].outputs[0].text


