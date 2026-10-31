# DataMate — Các vòng thi và hướng dẫn nộp bài

## 1. Round 1 — Public test

Đội phát triển giải pháp, chạy trên public test và tải `submission.jsonl` lên leaderboard. Điểm public chỉ để tham khảo trong quá trình phát triển. Không dùng public test để train hoặc thu thập đáp án test; xem [CONSTRAINTS.md](CONSTRAINTS.md).

## 2. Nộp và đóng băng giải pháp

Trước hạn nộp giải pháp, đội nộp **Docker image** chứa giải pháp hoàn chỉnh, gồm training code, inference code và dữ liệu/artifact cần bàn giao, theo Docker guideline của ban tổ chức. Theo hướng dẫn nộp đã cung cấp, file Docker package được chia sẻ bằng **link Google Drive công khai** kèm **checksum**, qua form **Solution Submission** trên cổng Zalo AI Challenge. Hạn nộp được nêu là **16/11**.

Giải pháp được **đóng băng** sau khi nộp image cuối. Thông tin còn cần đối chiếu với Docker guideline riêng gồm base image cụ thể, cách xuất image và yêu cầu đối với log.

## 3. Hợp đồng chạy container

Khi chấm, ban tổ chức mount tập test vào `/data` và lấy file kết quả tại `/result/submission.jsonl`. `/data` chỉ đọc; file tạm phải ghi bên ngoài thư mục này. Container phải tự chạy inference và xuất kết quả đúng định dạng trong [EVALUATION.md](EVALUATION.md), không cần thao tác thủ công và không có mạng.

Nếu lần chạy lại vượt giới hạn 6 giờ hoặc dừng sớm, chỉ các đáp án đã được ghi vào `/result/submission.jsonl` trước lúc dừng được chấm; các câu còn lại được tính là `abstain`.

## 4. Round 2 — Private test và điểm cuối

Sau khi giải pháp được đóng băng, ban tổ chức phát hành private test. Đội chạy **chính giải pháp đã đóng băng** trên bộ dữ liệu đó và tải `submission.jsonl` lên. Kết quả tải lên chỉ tạo leaderboard tạm thời và xác định các đội được chạy lại.

**Điểm cuối** là điểm ban tổ chức chạy lại Docker image đã nộp trên private test. Hai lần chạy phải đủ tái lập: `|PA(uploaded) − PA(re-run)| ≤ 0.03`. Nếu chênh lệch lớn hơn, ban tổ chức sẽ xem log, có thể chạy lại thêm một lần và yêu cầu đội giải trình; nếu không giải thích được, bài dự thi bị loại.
