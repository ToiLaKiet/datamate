"""CLI entrypoint for DataMate inference."""

import argparse
from importlib import import_module
from pathlib import Path

from src.llm.modalcomputes import ModalLLM  
from src.llm import MLXLLM, VLLMLLM
from src.pipeline import InferencePipeline

run_dataset = import_module("src.test-inference").run_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DataMate inference")
    parser.add_argument("--dataset", type=Path, required=True, help="Folder containing questions.jsonl and data/")
    parser.add_argument("--model", required=True, help="Local model directory or compatible model ID")
    parser.add_argument("--runtime", choices=("mlx", "vllm", "modal"), default="mlx", help="LLM inference backend")
    parser.add_argument("--max-model-len", type=int, default=16384, help="vLLM context limit in tokens")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.85, help="Local vLLM GPU memory fraction")
    parser.add_argument("--tensor-parallel-size", type=int, default=1, help="Number of local NVIDIA GPUs for vLLM")
    parser.add_argument("--quantization", help="Local vLLM quantization method, e.g. modelopt_fp4")
    parser.add_argument("--modal-app", default="datamate", help="Deployed Modal App name")
    parser.add_argument("--modal-environment", help="Modal Environment name, if not the active default")
    parser.add_argument("--output", type=Path, default=Path("submission.jsonl"))
    parser.add_argument("--limit", type=int, help="Process only the first N questions")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Generation cap for each LLM stage")
    parser.add_argument("--debug-dir", type=Path, help="Write a trace JSON file for each question")
    args = parser.parse_args()

    if args.runtime == "modal":
        llm = ModalLLM(
            args.model,
            app_name=args.modal_app,
            environment_name=args.modal_environment,
            max_model_len=args.max_model_len,
        )
    elif args.runtime == "vllm":
        llm = VLLMLLM(
            args.model,
            max_model_len=args.max_model_len,
            gpu_memory_utilization=args.gpu_memory_utilization,
            tensor_parallel_size=args.tensor_parallel_size,
            quantization=args.quantization,
        )
    else:
        llm = MLXLLM(args.model)
    pipeline = InferencePipeline(llm, max_tokens=args.max_tokens)
    run_dataset(args.dataset, args.output, pipeline, limit=args.limit, debug_dir=args.debug_dir)


if __name__ == "__main__":
    main()
