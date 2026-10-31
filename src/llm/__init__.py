"""Local language model inference backends."""

from importlib import import_module

from .base import BaseLLM

MLXLLM = import_module(".mlx-qwen3-8b", __name__).MLXLLM

__all__ = ["BaseLLM", "MLXLLM"]
