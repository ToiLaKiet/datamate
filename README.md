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

Nhóm `mlx` dành cho inference trên Mac. Backend CUDA dùng khi đóng gói Docker sẽ có dependencies riêng.

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
