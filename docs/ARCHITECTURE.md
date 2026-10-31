# DataMate — luồng inference dự kiến

Tài liệu này mô tả ranh giới các module của bản chạy thử. Các module trong sơ đồ đã có code; độ chính xác của hai lượt lập kế hoạch LLM cần được đo trên bộ train.

## 1. `llm` — gọi model

```mermaid
flowchart LR
    A[Đường dẫn model] --> B[Khởi tạo LLM một lần]
    C[Pipeline: messages và tham số sinh] --> D[LLM.infer]
    B --> D
    D --> E[Text trả về pipeline]
```

Pipeline chỉ cần một đối tượng tuân theo hợp đồng `BaseLLM.infer`. Cách nạp và chạy model nằm bên trong module `llm`; sơ đồ này không phụ thuộc vào runtime cụ thể.

## 2. `catalog` — nạp dữ liệu doanh nghiệp

```mermaid
flowchart LR
    A[Thư mục business_id] --> B[Đọc README]
    A --> C[CSV / Excel / SQLite]
    C --> D[Chuẩn hóa tên bảng và kiểu cột]
    D --> E[Các bảng SQL tạm trong tiến trình]
    B --> F[Schema catalog: nguồn, bảng, cột, ý nghĩa]
    D --> F
    F --> G[Pipeline dùng để lập truy vấn]
    E --> H[SQL executor chạy truy vấn]
```

“Bảng SQL tạm” nghĩa là chương trình đọc các file CSV/Excel/SQLite của một công ty và tạo bảng DuckDB để truy vấn ngay trong tiến trình inference. Đây không phải database server hay nơi lưu dữ liệu lâu dài. Mỗi công ty chỉ nạp một lần trong một phiên chạy. Catalog giữ liên hệ từ bảng SQL về file và sheet gốc để có thể kiểm tra truy vấn. Database tạm nằm ngoài dataset và được xóa sau phiên chạy.

## 3. `calendar` — giải nghĩa thời gian âm lịch

```mermaid
flowchart LR
    A[Kế hoạch lượt 1: yêu cầu tra lịch] --> B[Tra calendar.csv]
    B --> C[Ngày/khoảng ngày dương lịch]
    C --> D[Kế hoạch đã giải thời gian]
    D --> E[LLM lượt 2]
```

LLM chỉ nhận diện nhu cầu tra lịch; code xác định ngày. Nếu ngày cần tra nằm ngoài dữ liệu lịch, pipeline đánh dấu thiếu căn cứ.

## 4. `pipeline` — điều phối một câu hỏi

```mermaid
flowchart TD
    A[Question + as_of_date] --> B[Chọn luật liên quan]
    B --> C[LLM lượt 1: kế hoạch JSON]
    C --> D[Calendar resolver nếu cần]
    D --> E[README + schema catalog]
    E --> F[LLM lượt 2: SQL và mapping]
    F --> G[Kiểm tra SQL chỉ đọc]
    G --> H[Thực thi SQL]
    H --> I[Answer formatter]
    I --> J[Submission record]
```

Lượt 1 mô tả phép tính, luật, khoảng thời gian, bộ lọc, đơn vị và kiểu đáp án. Lượt 2 nối kế hoạch với bảng/cột thật. Kết quả SQL được kiểm tra trước khi xuất đáp án.

## 5. `answer` — định dạng và kiểm tra đáp án

```mermaid
flowchart LR
    A[Giá trị từ SQL + answer type] --> B[Kiểm tra kiểu]
    B --> C[Làm tròn theo loại số / chuẩn hóa ngày]
    C --> D[Record: id, type, answer]
    D --> E[JSONL UTF-8]
```

`number` yêu cầu phân biệt `money`, `count` và `decimal`. `percent` dùng thang 0–100. `unanswerable` và `abstain` không có `answer`. Thứ tự của `list` và `table` được giữ nguyên; pipeline phải tính đúng thứ tự theo rulebook trước khi gọi formatter.

## 6. `main.py` và `test_inference` — chạy một tập câu hỏi

```mermaid
flowchart TD
    X[CLI: main.py --dataset --model --output --limit] --> A[Runner: test_inference]
    A --> B[Đọc rulebook và calendar một lần thành ngữ cảnh chung]
    A --> C[Lấy câu hỏi tiếp theo từ questions.jsonl]
    C --> D[Chọn business_id và lấy README/catalog]
    B -->|ngữ cảnh chung| E[Pipeline xử lý đúng một câu hỏi]
    C -->|question và as_of_date| E
    D -->|ngữ cảnh công ty| E
    E --> F[Formatter trả về một submission record]
    F --> G[Append một dòng vào submission.jsonl]
    G --> C
```

`main.py` là entrypoint duy nhất. `--dataset` trỏ đến thư mục gốc chứa `questions.jsonl`, `rulebook.md`, `calendar.csv` và `data/<business_id>/`. `--model` nhận đường dẫn model MLX; `--output` là đường dẫn JSONL; `--limit` giới hạn số câu khi thử nhanh. Rulebook và calendar được đọc một lần để dùng lại; runner chỉ ghi một dòng sau khi pipeline hoàn tất câu hỏi tương ứng. Lỗi ở một câu được ghi ra stderr và câu đó được đánh dấu `abstain`.
