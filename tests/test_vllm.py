"""The CUDA adapter can be checked without loading GPU weights."""

import sys
import types
import unittest
from unittest.mock import patch

from src.llm import VLLMLLM
from src.main import main


class VLLMLLMTests(unittest.TestCase):
    def test_loads_once_and_passes_chat_and_sampling_options(self):
        instances = []

        class FakeLLM:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.calls = []
                instances.append(self)

            def chat(self, conversations, *, sampling_params, use_tqdm):
                self.calls.append((conversations, sampling_params, use_tqdm))
                return [types.SimpleNamespace(outputs=[types.SimpleNamespace(text="answer")])]

        class FakeSamplingParams:
            def __init__(self, **kwargs):
                self.options = kwargs

        fake_module = types.ModuleType("vllm")
        fake_module.LLM = FakeLLM
        fake_module.SamplingParams = FakeSamplingParams

        with patch.dict(sys.modules, {"vllm": fake_module}):
            backend = VLLMLLM(
                "/models/chat", max_model_len=8192,
                gpu_memory_utilization=0.8, tensor_parallel_size=2,
                quantization="modelopt_fp4",
            )
            messages = [{"role": "user", "content": "Xin chào"}]
            self.assertEqual(backend.infer(messages, max_tokens=32, temperature=0), "answer")
            self.assertEqual(backend.infer(messages, max_tokens=48, temperature=0.4), "answer")

        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].options, {
            "model": "/models/chat", "max_model_len": 8192,
            "gpu_memory_utilization": 0.8, "tensor_parallel_size": 2,
            "dtype": "auto", "quantization": "modelopt_fp4",
        })
        self.assertEqual(len(instances[0].calls), 2)
        self.assertEqual(instances[0].calls[0][0], [messages])
        self.assertEqual(instances[0].calls[0][1].options, {"max_tokens": 32, "temperature": 0})
        self.assertFalse(instances[0].calls[0][2])
        self.assertEqual(instances[0].calls[1][1].options, {"max_tokens": 48, "temperature": 0.4})

    def test_rejects_invalid_inference_options(self):
        backend = object.__new__(VLLMLLM)
        with self.assertRaisesRegex(ValueError, "messages"):
            backend.infer([])
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            backend.infer([{"role": "user", "content": "hi"}], max_tokens=0)
        with self.assertRaisesRegex(ValueError, "temperature"):
            backend.infer([{"role": "user", "content": "hi"}], temperature=-1)
        with self.assertRaisesRegex(ValueError, "thinking_token_budget"):
            backend.infer([{"role": "user", "content": "hi"}], thinking_token_budget=0)

    def test_deepseek_uses_json_constraint_and_reasoning_budget(self):
        captured = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured["model_options"] = kwargs

            def chat(self, conversations, *, sampling_params, use_tqdm):
                captured["sampling_options"] = sampling_params.options
                return [types.SimpleNamespace(outputs=[types.SimpleNamespace(text='{"status":"ok"}')])]

        class FakeParams:
            def __init__(self, **kwargs):
                self.options = kwargs

        class FakeReasoningConfig:
            def __init__(self, **kwargs):
                self.options = kwargs

        class FakeStructuredOutputsParams:
            def __init__(self, **kwargs):
                self.options = kwargs

        fake_vllm = types.ModuleType("vllm")
        fake_vllm.LLM = FakeLLM
        fake_vllm.SamplingParams = FakeParams
        fake_config = types.ModuleType("vllm.config")
        fake_config.ReasoningConfig = FakeReasoningConfig
        fake_sampling = types.ModuleType("vllm.sampling_params")
        fake_sampling.StructuredOutputsParams = FakeStructuredOutputsParams
        with patch.dict(sys.modules, {"vllm": fake_vllm, "vllm.config": fake_config,
                                      "vllm.sampling_params": fake_sampling}):
            backend = VLLMLLM("deepseek-ai/DeepSeek-R1-0528-Qwen3-8B")
            backend.infer([{"role": "user", "content": "hi"}], max_tokens=4096,
                          output_schema={"type": "object"}, thinking_token_budget=1024)

        self.assertEqual(captured["model_options"]["reasoning_config"].options,
                         {"reasoning_start_str": "<think>", "reasoning_end_str": "</think>"})
        self.assertEqual(captured["sampling_options"]["thinking_token_budget"], 1024)
        self.assertEqual(captured["sampling_options"]["structured_outputs"].options,
                         {"json": {"type": "object"}})

    def test_cli_selects_vllm_and_passes_gpu_settings(self):
        argv = [
            "datamate", "--dataset", "data/train", "--model", "/models/chat",
            "--runtime", "vllm", "--max-model-len", "8192",
            "--gpu-memory-utilization", "0.8", "--tensor-parallel-size", "2",
            "--quantization", "modelopt_fp4",
        ]
        with patch.object(sys, "argv", argv), \
             patch("src.main.VLLMLLM") as backend, \
             patch("src.main.MLXLLM") as mlx_backend, \
             patch("src.main.run_dataset") as runner:
            main()

        backend.assert_called_once_with(
            "/models/chat", max_model_len=8192,
            gpu_memory_utilization=0.8, tensor_parallel_size=2,
            quantization="modelopt_fp4",
        )
        mlx_backend.assert_not_called()
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
