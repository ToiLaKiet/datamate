"""Local text generation with an MLX-compatible language model."""

from collections.abc import Mapping, Sequence

from .base import BaseLLM

class MLXLLM(BaseLLM):
    """Load one model once and reuse it across inference calls.

    ``model_id`` may be a local model directory or an MLX-compatible
    Hugging Face repository ID.
    """

    def __init__(self, model_id: str) -> None:
        if not model_id:
            raise ValueError("model_id must not be empty")

        from mlx_lm import load

        self.model_id = model_id
        self.model, self.tokenizer = load(model_id)

    def infer(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        """Return the model's response to a chat conversation as plain text."""
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature < 0:
            raise ValueError("temperature must not be negative")
        if self.tokenizer.chat_template is None:
            raise ValueError(f"Model {self.model_id!r} has no chat template")

        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler
        import mlx.core as mx

        prompt = self.tokenizer.apply_chat_template(
            [dict(message) for message in messages],
            tokenize=False,
            add_generation_prompt=True,
        )
        try:
            return generate(
                self.model,
                self.tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=make_sampler(temp=temperature),
                prefill_step_size=256,
                verbose=False,
            )
        finally:
            mx.clear_cache()
