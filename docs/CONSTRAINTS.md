# DataMate — Ràng buộc kỹ thuật

Tài liệu này ghi các yêu cầu kỹ thuật của cuộc thi đối với giải pháp. Cách nộp và chấm điểm cuối nằm trong [SUBMISSION.md](SUBMISSION.md); cách tính điểm từng câu nằm trong [EVALUATION.md](EVALUATION.md).

## 1. Đội thi

Tư cách tham gia và các quy định chung tuân theo quy chế Zalo AI Challenge 2026.

## 2. Model

- Chỉ dùng model có weights được phát hành công khai **trước 01/10/2026** theo giấy phép cho phép sử dụng; được fine-tune.
- Tổng số tham số của **mọi model dùng khi inference** (LLM, embedding, reranker, classifier, v.v.) không quá **15 tỷ**, dù các model không được nạp cùng lúc.
- Với mixture-of-experts, tính **toàn bộ** tham số của model. Quantization được phép nhưng không làm giảm số tham số được tính.
- Phải khai báo các model đã dùng trong [README.md ở thư mục gốc](../README.md).

## 3. Inference offline

Inference phải chạy hoàn toàn bên trong Docker image. Container được chạy với mạng bị tắt: không gọi API LLM thương mại, không tải model hoặc dependency, không truy cập mạng dưới bất kỳ hình thức nào. Mọi weights, dependency và artifact cần cho inference phải có sẵn trong image.

## 4. Tự động hóa và thực thi code

- Hệ thống phải tạo đáp án không có người can thiệp. Cấm hard-code đáp án hoặc logic dựa trên `question` ID hay `business_id`.
- Agent có thể sinh và thực thi code bên trong container; đây là lựa chọn, không phải yêu cầu bắt buộc.
- `/data` được mount **chỉ đọc**; file tạm phải ghi ở nơi khác.

## 5. Dữ liệu được phép dùng

Được dùng dữ liệu train do ban tổ chức cung cấp, dữ liệu tự tổng hợp, bộ dữ liệu công khai và model công khai. **Không được dùng dữ liệu public/private test để train hoặc thu thập đáp án cho câu hỏi test bằng bất kỳ cách nào.** Việc chạy public test để đánh giá và nộp leaderboard được mô tả trong [SUBMISSION.md](SUBMISSION.md).

## 6. Tài nguyên và thời gian

Ban tổ chức xác minh giải pháp trên máy có **2 × NVIDIA RTX 5090**, mỗi GPU **32 GB VRAM**, và **512 GB RAM**. Toàn bộ private test phải được xử lý trong **6 giờ wall-clock**, bao gồm thời gian nạp model.

GPU Blackwell yêu cầu CUDA **≥ 12.8** cùng bản PyTorch/vLLM tương thích. Base image cụ thể phải theo Docker guideline của ban tổ chức; thông tin base image chưa có trong tài liệu repo này.
