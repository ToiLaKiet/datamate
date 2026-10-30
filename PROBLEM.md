DataMate challenges you to build an AI agent that answers natural-language Vietnamese questions directly on structured data (CSV, Excel, SQLite): given the raw files and a question, the agent returns a correct answer — or declines to answer when the data cannot support the question. 

Input:
 • A data package for one business: one or more files (.csv, .xlsx, .sqlite) plus a short README.md describing the business.
 • A question in everyday Vietnamese.
 • An as-of date: the “today” against which relative time expressions (“tháng này”, “tuần rồi”, “cùng kỳ năm ngoái”) are resolved.
 • A rulebook and a solar–lunar calendar, shared by every business of the split.

Output:
 • A final answer of one of the types in the Evaluation section: a value (number, percent, string, date, boolean, list, table, unanswerable - when the data cannot support the question, or abstain - when the agent chooses not to answer.

An example:
Input - one line of questions.jsonl:
{"id": "q_06de33fa21cc", "business_id": "biz_118", "question": "sp bán dc nhiều nhất tuần rồi là gì", "as_of_date": "2026-03-04"}
 
Output - one line of submission.jsonl:
{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg"}

Evaluation:

