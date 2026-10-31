# DataMate

DataMate là hệ thống trả lời câu hỏi tiếng Việt trên dữ liệu có cấu trúc của doanh nghiệp (CSV, Excel, SQLite). Hệ thống đọc câu hỏi cùng dữ liệu liên quan, áp dụng quy tắc nghiệp vụ và xuất đáp án có định dạng để chấm tự động.

## Tài liệu

- [Mô tả bài toán](docs/PROBLEM.md)
- [Quy tắc đánh giá](docs/EVALUATION.md)
- [Ràng buộc kỹ thuật](docs/CONSTRAINTS.md)
- [Các vòng thi và hướng dẫn nộp bài](docs/SUBMISSION.md)

## Môi trường phát triển trên Mac

Dependencies được quản lý bằng `uv` trong `pyproject.toml` và `uv.lock`. Cài nhóm MLX và chạy Python bằng:

```bash
uv sync --group mlx
uv run --group mlx python your_script.py
```

Nhóm `mlx` dành cho inference trên Mac. Backend CUDA dùng khi đóng gói Docker sẽ có dependencies riêng.
