# Set-up Modal for remote inference on NVIDIA GPUs. If Modal is unavailable, the code will still work for local inference.
from ..vllm import VLLMLLM

try:
    import modal
except ModuleNotFoundError as exc:
    if exc.name != "modal":
        raise
    modal = None

if modal is not None:
    app = modal.App("datamate")
    vllm_image = modal.Image.debian_slim(python_version="3.12").pip_install("vllm>=0.11")

    def _remote_tokenizer(model_id: str) -> str | None:
        if model_id != "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B":
            return None

        import json
        import shutil
        import tempfile
        from pathlib import Path

        from huggingface_hub import snapshot_download

        filenames = (
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "chat_template.jinja",
        )
        source = Path(snapshot_download(repo_id=model_id, allow_patterns=filenames))
        destination = Path(tempfile.mkdtemp(prefix="datamate-tokenizer-"))
        for filename in filenames:
            path = source / filename
            if path.is_file():
                shutil.copy2(path, destination / filename)

        config_path = destination / "tokenizer_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["tokenizer_class"] = "TokenizersBackend"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return str(destination)

    @app.cls(
        gpu="H100",
        memory=16384,
        image=vllm_image,
        env={"VLLM_USE_FLASHINFER_SAMPLER": "0"},
    )
    class RemoteVLLM:
        """Resolve model_id inside Modal, as a Hub ID or a mounted model path."""

        model_id: str = modal.parameter()
        max_model_len: int = modal.parameter(default=16384)

        @modal.enter()
        def load(self) -> None:
            self.backend = VLLMLLM(
                self.model_id,
                max_model_len=self.max_model_len,
                tokenizer_id=_remote_tokenizer(self.model_id),
            )

        @modal.method()
        def infer(
            self,
            messages: list[dict[str, str]],
            max_tokens: int = 512,
            temperature: float = 0.0,
        ) -> str:
            return self.backend.infer(
                messages, max_tokens=max_tokens, temperature=temperature
            )
