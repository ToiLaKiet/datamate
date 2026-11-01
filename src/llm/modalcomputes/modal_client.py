"""Call a deployed Modal inference class from the local DataMate pipeline."""

from collections.abc import Mapping, Sequence
from typing import Any

from ..base import BaseLLM


class ModalLLM(BaseLLM):
    """Reuse one deployed RemoteVLLM handle across pipeline calls."""

    def __init__(
        self,
        model_id: str,
        *,
        app_name: str = "datamate",
        environment_name: str | None = None,
        max_model_len: int = 16384,
    ) -> None:
        if not model_id:
            raise ValueError("model_id must not be empty")
        if max_model_len < 1:
            raise ValueError("max_model_len must be positive")

        try:
            import modal
        except ImportError as exc:
            raise RuntimeError("Modal client is unavailable; run with `uv run --with modal`") from exc

        remote_class = modal.Cls.from_name(
            app_name, "RemoteVLLM", environment_name=environment_name
        )
        self._remote = remote_class(model_id=model_id, max_model_len=max_model_len)

    def infer(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        output_schema: dict[str, Any] | None = None,
        thinking_token_budget: int | None = None,
    ) -> str:
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature < 0:
            raise ValueError("temperature must not be negative")
        if thinking_token_budget is not None and thinking_token_budget < 1:
            raise ValueError("thinking_token_budget must be positive")

        try:
            options: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}
            if output_schema is not None:
                options["output_schema"] = output_schema
            if thinking_token_budget is not None:
                options["thinking_token_budget"] = thinking_token_budget
            return self._remote.infer.remote(
                [dict(message) for message in messages],
                **options,
            )
        except Exception as exc:
            raise RuntimeError(f"Modal inference failed: {exc}") from exc
