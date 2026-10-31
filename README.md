# DataMate

DataMate là hệ thống trả lời câu hỏi tiếng Việt trên dữ liệu có cấu trúc của doanh nghiệp (CSV, Excel, SQLite). Hệ thống đọc câu hỏi cùng dữ liệu liên quan, áp dụng quy tắc nghiệp vụ và xuất đáp án có định dạng để chấm tự động.

## Tài liệu

- [Mô tả bài toán](docs/PROBLEM.md)
- [Quy tắc đánh giá](docs/EVALUATION.md)
- [Ràng buộc kỹ thuật](docs/CONSTRAINTS.md)
- [Các vòng thi và hướng dẫn nộp bài](docs/SUBMISSION.md)
- [Sơ đồ luồng inference theo module](docs/ARCHITECTURE.md)

## Môi trường phát triển trên Mac

Dependencies được quản lý bằng `uv` trong `pyproject.toml` và `uv.lock`. Cài nhóm MLX và chạy Python bằng:

```bash
uv sync --group mlx
uv run --group mlx python your_script.py
```

Nhóm `mlx` dành cho inference trên Mac. Nhóm `cuda` cài vLLM trên Linux x86_64 có NVIDIA GPU.

Chạy thử pipeline trên 1 câu train (không mở API server):

```bash
uv run --group mlx python -m src.main \
  --dataset data/train \
  --model data/models/DeepSeek-R1-0528-Qwen3-8B-4bit \
  --output /tmp/datamate-submission.jsonl \
  --debug-dir /tmp/datamate-debug \
  --limit 1
```

`--debug-dir` lưu kế hoạch hai lượt LLM, SQL và thông tin kết quả để kiểm tra lỗi. Runner ghi đáp án sau từng câu; nếu một câu lỗi, nó ghi `abstain` và tiếp tục.

## Inference trên NVIDIA

Trên máy Linux có NVIDIA GPU, cài nhóm CUDA và chạy cùng pipeline bằng vLLM trực tiếp trong Python:

```bash
uv sync --locked --group cuda
uv run --locked --group cuda python -m src.main \
  --runtime vllm \
  --dataset data/train \
  --model /path/to/vllm-compatible-model \
  --output /tmp/datamate-submission.jsonl \
  --limit 1
```

`--tensor-parallel-size 2` dùng hai GPU nếu model cần chia weights. `--max-model-len` (mặc định 16384) và `--gpu-memory-utilization` (mặc định 0.85) điều chỉnh giới hạn context và phần VRAM mà vLLM sử dụng. Model truyền qua `--model` phải ở định dạng vLLM hỗ trợ; thư mục `data/models/DeepSeek-R1-0528-Qwen3-8B-4bit` là bản quant MLX nên không dùng trực tiếp cho vLLM. Không cần chạy API server.
