"""Shared interface for chat model backends."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence


class BaseLLM(ABC):
    """Return a plain-text answer for a chat conversation."""

    @abstractmethod
    def infer(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        """Generate one response from the supplied messages."""
