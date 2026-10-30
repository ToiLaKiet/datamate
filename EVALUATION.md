# DataMate — Hướng dẫn đánh giá

Tài liệu này tóm tắt **đúng phần quy tắc đánh giá đã được cung cấp**: chấm từng câu, đối chiếu theo kiểu đáp án, câu hỏi xếp hạng, điểm Penalized Accuracy (PA) và xử lý đồng điểm giữa các đội. Những quy tắc cụ thể của từng doanh nghiệp (chẳng hạn đơn hàng nào hợp lệ hoặc tiêu chí xếp hạng mặc định) phải tra trong rulebook tương ứng; tài liệu này không tự đặt thêm mặc định.

## 1. Kết quả chấm của một câu

Mỗi câu nhận đúng một trong ba kết quả:

| Kết quả | Điều kiện | Điểm thành phần `s_i` |
| --- | --- | ---: |
| `correct` | Kiểu (`type`) khớp kiểu tham chiếu **và** giá trị khớp theo quy tắc của kiểu đó. | +1 |
| `wrong` | Có nộp đáp án khác `abstain`, nhưng kiểu hoặc giá trị không khớp. | −1 |
| `abstain` | Nộp `type: "abstain"` hoặc thiếu hẳn đáp án cho câu đó. | 0 |

**Không có điểm một phần.** Ví dụ, trả đúng các phần tử nhưng sai thứ tự của `list` vẫn là `wrong`.

`unanswerable` và `abstain` khác nhau:

- `unanswerable` là một **kiểu đáp án**: dữ liệu không chứa thông tin cần thiết. Nó chỉ được `correct` khi kiểu tham chiếu cũng là `unanswerable`; nếu đáp án tham chiếu trả lời được thì `wrong`.
- `abstain` là lựa chọn **không đưa ra đáp án**. Nó được chấm `abstain` bất kể đáp án tham chiếu là gì.
- Câu “Any answer given to an unanswerable question counts as wrong” được hiểu cùng với bảng đối chiếu: nếu tham chiếu là `unanswerable`, một câu trả lời nội dung cụ thể (số, tên, danh sách, v.v.) là `wrong`; nộp `unanswerable` là `correct`, còn `abstain` là `abstain`.

## 2. Quy tắc đối chiếu theo `type`

| `type` | Nội dung đáp án | Cách đối chiếu |
| --- | --- | --- |
| `number` | Số, ví dụ tiền VND, số lượng, số đếm. | Khớp chính xác. Giá trị tham chiếu là số nguyên hoặc đã được làm tròn đến 2 chữ số thập phân. |
| `percent` | Giá trị phần trăm, ví dụ `-12.45`. | Khớp chính xác **sau khi làm tròn đến 2 chữ số thập phân**; dấu âm/dương phải đúng. |
| `string` | Tên sản phẩm, khách hàng, chi nhánh, thứ trong tuần, v.v. | Chuẩn hóa cả đáp án và từng dạng được chấp nhận của tham chiếu rồi so sánh bằng nhau; xem chi tiết bên dưới. |
| `date` | Ngày hoặc tháng. | Khớp chính xác: ngày `yyyy-mm-dd`; câu hỏi về tháng dùng `yyyy-mm`. |
| `boolean` | `true` hoặc `false`. | Khớp chính xác. |
| `list` | Danh sách tên hoặc số. | **Luôn xét thứ tự**, so khớp từng phần tử theo vị trí. Thứ tự theo yêu cầu câu hỏi, hoặc mặc định của rulebook nếu câu hỏi không nói. Phần tử dùng quy tắc `string`/`number` tương ứng. |
| `table` | Đối tượng gồm `columns` và `rows`. | Tên cột so bằng tên đã chuẩn hóa; nếu tên cột không khớp thì xét theo vị trí. Hàng được so như một tập hợp, không xét thứ tự hàng. Ô tên dùng quy tắc `string`, ô số dùng quy tắc `number`. |
| `unanswerable` | Dữ liệu không có điều cần thiết để trả lời. | Đúng khi và chỉ khi kiểu tham chiếu là `unanswerable`. |
| `abstain` | Agent chọn không trả lời. | Luôn được chấm `abstain`, không phụ thuộc tham chiếu. |

### Chuẩn hóa `string`

Trước khi so sánh, cả chuỗi nộp và **từng dạng tham chiếu được chấp nhận** đều trải qua đúng thứ tự sau:

1. Chuẩn hóa Unicode **NFC**.
2. Chuyển thành chữ thường.
3. Thay từng ký tự **không phải chữ cái, chữ số hoặc khoảng trắng** bằng một dấu cách.
4. Bỏ khoảng trắng ở đầu/cuối và gộp các dãy khoảng trắng liên tiếp thành một dấu cách.

**Không bỏ dấu tiếng Việt.** Mỗi tham chiếu có thể chấp nhận các cách viết của tên thực sự xuất hiện trong dữ liệu doanh nghiệp đó và mã của nó, sau khi chuẩn hóa. Không tự giả định mọi tên gần giống nhau đều được chấp nhận.

## 3. Câu hỏi xếp hạng (`Ranking questions`)

1. Lấy tiêu chí xếp hạng trong câu hỏi; nếu không có, dùng **mặc định trong rulebook**.
2. Chỉ xét **các đơn hàng hợp lệ** theo rulebook.
3. Xếp **giảm dần** theo giá trị của tiêu chí. Nếu cùng giá trị, xếp **tăng dần theo mã**.
4. Nếu số ứng viên hợp lệ **ít hơn `k`**, đáp án tham chiếu gồm **tất cả** ứng viên đó.
5. Ban tổ chức **loại khỏi tập test khi tạo đề** các câu mà bảng xếp hạng tham chiếu có đồng giá trị ở ranh giới top-`k` (hoặc đồng hạng 1 với câu hỏi “... nhất”). Thí sinh vẫn xử lý mọi câu thực sự có mặt trong test; không tự bỏ câu, không tự chuyển tình huống đồng hạng thành `unanswerable`.

Ví dụ, với top 3 và các giá trị `100, 90, 80, 80`, hạng 3 và 4 bằng nhau nên câu hỏi thuộc trường hợp BTC nói sẽ loại khỏi tập test. Việc dùng mã để sắp hai đơn cùng giá trị **không xóa** tình trạng đồng hạng theo giá trị ở ranh giới.

## 4. Điểm trên toàn tập test

Với `N` câu, chỉ số trên leaderboard là **Penalized Accuracy**:

$$
\mathrm{PA}=\frac{1}{N}\sum_{i=1}^{N}s_i,\qquad
s_i=\begin{cases}
+1 & \text{nếu câu }i\text{ correct}\\
0 & \text{nếu câu }i\text{ abstain}\\
-1 & \text{nếu câu }i\text{ wrong.}
\end{cases}
$$

Tương đương: **`PA = (số câu correct − số câu wrong) / N`**. Mọi câu có trọng số như nhau. Ví dụ 10 câu đúng, 3 câu sai, 2 câu abstain trong 15 câu cho `PA = (10 − 3) / 15 ≈ 0.4667`.

Vì trả sai bị **−1** còn `abstain` được **0**, không nên đoán khi không có đủ căn cứ. Nếu một quyết định có xác suất đúng được ước lượng là `p` và chỉ xét ba mức điểm trên, kỳ vọng điểm của việc trả lời là `2p − 1`; nó cao hơn abstain khi `p > 0.5`. Đây là **suy luận chiến lược từ công thức điểm**, không phải một ngưỡng bắt buộc được BTC quy định; ước lượng `p` của agent có thể sai.

## 5. Khi các đội bằng điểm

Nếu các đội bằng thứ hạng cuối theo PA, BTC xét lần lượt:

1. **Tổng thời gian suy luận** trong lần BTC chạy lại: thời gian thấp hơn xếp trên.
2. Nếu vẫn bằng nhau: **bài nộp sớm hơn** xếp trên.

Đây là quy tắc **xếp hạng đội thi**, tách biệt với quy tắc xếp hạng đơn hàng trong một câu hỏi.

## 6. Checklist trước khi xuất đáp án

- `type` có đúng loại mà câu hỏi yêu cầu không?
- Giá trị có được tính từ đúng dữ liệu và đúng rulebook không?
- Số/ngày/phần trăm có đúng định dạng và độ chính xác cần so khớp không?
- Với `list`, số phần tử và **thứ tự từng vị trí** có đúng không?
- Với `table`, tên cột và nội dung các hàng có đúng không?
- Nếu dữ liệu thiếu thông tin cần thiết, đã phân biệt `unanswerable` với `abstain` chưa?
