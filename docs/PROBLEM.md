# DataMate — Mô tả bài toán

## 1. Mục tiêu

Xây dựng một AI agent trả lời câu hỏi tiếng Việt về dữ liệu có cấu trúc của từng doanh nghiệp. Agent nhận dữ liệu gốc dạng CSV, Excel hoặc SQLite và trả về đáp án có thể kiểm chứng từ dữ liệu. Nếu dữ liệu không đủ để trả lời, agent phải nhận ra điều đó.

## 2. Đầu vào

Mỗi câu hỏi đi kèm:

| Thành phần | Mô tả |
| --- | --- |
| Gói dữ liệu doanh nghiệp | Một hoặc nhiều file `.csv`, `.xlsx`, `.sqlite` và một `README.md` mô tả dữ liệu của doanh nghiệp. |
| Câu hỏi | Câu hỏi bằng tiếng Việt thông dụng. |
| `as_of_date` | Ngày được xem là “hôm nay” khi diễn giải các cụm thời gian tương đối như “tháng này”, “tuần rồi”, “cùng kỳ năm ngoái”. |
| `rulebook.md` và `calendar.csv` | Quy tắc nghiệp vụ và lịch dương–âm dùng chung cho các doanh nghiệp trong cùng tập dữ liệu. |

Trong bộ dữ liệu hiện có, mỗi dòng của `questions.jsonl` chứa `id`, `business_id`, `question` và `as_of_date`; dữ liệu của doanh nghiệp nằm trong `data/<business_id>/`.

## 3. Đầu ra

Mỗi đáp án được nộp là một dòng JSON trong `submission.jsonl`, giữ nguyên `id` và ghi `type` cùng giá trị theo đúng định dạng trong [EVALUATION.md](EVALUATION.md) và `rulebook.md` của tập dữ liệu. Có thể bỏ dòng của câu mà agent chọn `abstain`.

Các kiểu đáp án gồm `number`, `percent`, `string`, `date`, `boolean`, `list`, `table`, `unanswerable` và `abstain`. `unanswerable` nghĩa là dữ liệu không hỗ trợ câu trả lời; `abstain` nghĩa là agent chọn không trả lời. Hai kiểu này có cách chấm khác nhau.

## 4. Ví dụ

Một dòng trong `questions.jsonl`:

```json
{"id":"q_06de33fa21cc","business_id":"biz_118","question":"sp bán dc nhiều nhất tuần rồi là gì","as_of_date":"2026-03-04"}
```

Dòng tương ứng trong `submission.jsonl`:

```json
{"id":"q_06de33fa21cc","type":"string","answer":"Xi măng Hà Tiên PCB40 bao 50kg"}
```

## 5. Đánh giá

Xem [EVALUATION.md](EVALUATION.md) để biết cách đối chiếu từng kiểu đáp án và tính điểm. Các quy tắc nghiệp vụ cụ thể nằm trong `rulebook.md` của từng tập dữ liệu.

