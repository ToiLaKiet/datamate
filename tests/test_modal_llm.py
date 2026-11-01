"""The dataset CLI can route inference to a deployed Modal class."""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from src.llm import ModalLLM
from src.main import main


class ModalLLMTests(unittest.TestCase):
    def test_reuses_remote_class_and_passes_plain_messages(self):
        remote = MagicMock()
        remote.infer.remote.return_value = "answer"
        remote_class = MagicMock(return_value=remote)
        from_name = MagicMock(return_value=remote_class)
        fake_modal = types.ModuleType("modal")
        fake_modal.Cls = types.SimpleNamespace(from_name=from_name)

        with patch.dict(sys.modules, {"modal": fake_modal}):
            llm = ModalLLM(
                "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
                app_name="datamate",
                environment_name="main",
                max_model_len=8192,
            )
            messages = [{"role": "user", "content": "Xin chào"}]
            self.assertEqual(
                llm.infer(messages, max_tokens=64, temperature=0.2), "answer"
            )
            self.assertEqual(llm.infer(messages), "answer")
            self.assertEqual(llm.infer(messages, output_schema={"type": "object"},
                                       thinking_token_budget=1024), "answer")

        from_name.assert_called_once_with(
            "datamate", "RemoteVLLM", environment_name="main"
        )
        remote_class.assert_called_once_with(
            model_id="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", max_model_len=8192
        )
        self.assertEqual(remote.infer.remote.call_count, 3)
        remote.infer.remote.assert_any_call(
            [{"role": "user", "content": "Xin chào"}],
            max_tokens=64,
            temperature=0.2,
        )
        remote.infer.remote.assert_any_call(
            [{"role": "user", "content": "Xin chào"}],
            max_tokens=512, temperature=0.0,
            output_schema={"type": "object"}, thinking_token_budget=1024,
        )

    def test_cli_selects_deployed_modal_backend(self):
        argv = [
            "datamate", "--dataset", "data/train",
            "--model", "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            "--runtime", "modal", "--max-model-len", "8192",
            "--modal-app", "datamate", "--modal-environment", "main",
            "--max-tokens", "5000", "--stage1-thinking-tokens", "768",
            "--stage2-thinking-tokens", "1536",
        ]
        with patch.object(sys, "argv", argv), \
             patch("src.main.ModalLLM") as backend, \
             patch("src.main.InferencePipeline") as pipeline_cls, \
             patch("src.main.run_dataset") as runner:
            main()

        backend.assert_called_once_with(
            "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            app_name="datamate",
            environment_name="main",
            max_model_len=8192,
        )
        pipeline_cls.assert_called_once_with(
            backend.return_value, max_tokens=5000,
            stage1_thinking_tokens=768, stage2_thinking_tokens=1536,
        )
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
