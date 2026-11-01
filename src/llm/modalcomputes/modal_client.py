"""Call a deployed Modal inference class from the local DataMate pipeline."""

from collections.abc import Mapping, Sequence

from .base import BaseLLM


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
    ) -> str:
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if temperature < 0:
            raise ValueError("temperature must not be negative")

        try:
            return self._remote.infer.remote(
                [dict(message) for message in messages],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise RuntimeError(f"Modal inference failed: {exc}") from exc
