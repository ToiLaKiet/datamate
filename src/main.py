"""CLI entrypoint for offline DataMate inference."""

import argparse
from pathlib import Path

from src.llm import MLXLLM
from src.pipeline import InferencePipeline
from src.test_inference import run_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline DataMate inference")
    parser.add_argument("--dataset", type=Path, required=True, help="Folder containing questions.jsonl and data/")
    parser.add_argument("--model", required=True, help="Local MLX model directory or compatible model ID")
    parser.add_argument("--output", type=Path, default=Path("submission.jsonl"))
    parser.add_argument("--limit", type=int, help="Process only the first N questions")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Generation cap for each LLM stage")
    parser.add_argument("--debug-dir", type=Path, help="Write a trace JSON file for each question")
    args = parser.parse_args()

    llm = MLXLLM(args.model)
    pipeline = InferencePipeline(llm, max_tokens=args.max_tokens)
    run_dataset(args.dataset, args.output, pipeline, limit=args.limit, debug_dir=args.debug_dir)


if __name__ == "__main__":
    main()
