# Benchmark & Observability Report — Day 14

**Họ tên:** Khuat Tien Minh (MSSV: 2A202603616)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 + WSL2 Ubuntu (Python 3.14.4, `os.name == 'posix'`), Docker Desktop 29.9.3, Docker Compose v5.7.0

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| --- | --- | --- |
| p95 latency `/ask` | `< 500 ms` | Đảm bảo 95% người dùng nhận phản hồi mượt (< 0.5 giây); khớp ngưỡng kiểm định của `load_test.py` và tránh che giấu tail latency như dùng average. |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để chịu lỗi upstream LLM ngẫu nhiên (~1% mặc định của mock LLM) mà không gây alert fatigue. |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau sửa KB: `100 %`, 0 regression) | Đảm bảo chất lượng trả lời trước khi merge/deploy thông qua CI quality gate (`.github/workflows/eval.yml`). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests/mức)

Nguồn dữ liệu: `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json`.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 4.07 | 192.6 | 224.2 | 1708.0 | 1.33% | ✅ PASS |
| 10 | 35.77 | 193.9 | 233.2 | 1706.2 | 0.67% | ✅ PASS |
| 50 | 60.03 | 301.4 | 1834.7 | 2981.7 | 1.33% | ❌ FAIL (p95 > 500ms) |
| 100 | 46.43 | 818.5 | 4204.8 | 4835.9 | 1.00% | ❌ FAIL (p95 > 500ms) |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency. Từ concurrency `1 → 10`, RPS tăng gần tuyến tính (`4.07 → 35.77 req/s`) trong khi p95 gần như không đổi (`224.2 → 233.2 ms`) vì 1 process uvicorn còn nhiều headroom. Nhưng lên `50` và `100`, RPS bão hòa rồi giảm (`60.03 → 46.43 req/s`), còn p50/p95/p99 tăng vọt (`p95 = 4204.8 ms` ở c=100) do hàng đợi (queueing delay) và bão hòa CPU/event loop trên 1 instance duy nhất.

### 2.2 Tail latency (`concurrency=20`, 300 requests/mức)

Nguồn dữ liệu: `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| --- | ---: | ---: | ---: |
| 0 | 194.7 | 227.7 | 265.3 |
| 0.03 (mặc định) | 206.3 | 229.5 | 323.4 |
| 0.1 | 359.8 | 1695.1 | 1711.6 |

**Nhận xét:** **p95 và p99** nhạy nhất với request chậm (tail latency). Khi tăng `MOCK_SLOW_RATE` từ `0` lên `0.1` (10% request chậm thêm 1500 ms), `avg` chỉ tăng từ `194.7 ms` lên `359.8 ms` (vẫn có vẻ thấp dưới 500 ms), nhưng **p95 nhảy vọt gấp 7.4 lần** (`227.7 → 1695.1 ms`) và **p99 nhảy lên `1711.6 ms`**, vi phạm SLO ngay lập tức. Vì vậy SLO phải đặt theo **p95/p99**, không đặt theo average (vốn che giấu trải nghiệm tệ của nhóm người dùng chậm nhất).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn dữ liệu: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| --- | --- | --- | --- |
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.1 | 109.3 | 113.8 |
| Tổng cost (USD) | $0.000405 | $0.000764 | $0.000792 |
| Cost / câu đúng (USD) | $0.00040455 | $0.00003639 | $0.00003443 |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS (0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
| --- | --- | --- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `["jwt"]` giải thích sự khác biệt giữa API key và JWT (token có chữ ký số, thông tin user, thời điểm hết hạn) vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `["hpa", "kubernetes", "autoscal"]` giải thích Kubernetes HPA scale pod dựa trên CPU, memory hoặc custom metrics vào `KNOWLEDGE_BASE`. |

**CI Quality Gate (Exercise 7.3):** Đã tạo workflow `.github/workflows/eval.yml` chạy `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85 --baseline reports/eval_v2.json` trên mỗi pull request. Khi kiểm thử ngược với agent v1 so với baseline v2, `run_eval.py` phát hiện 20 câu regression và trả **exit code `1`**, khiến job CI fail và chặn merge PR tự động.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
Agent v2 thêm bước retrieval (RAG) nên prompt dài hơn (avg tokens tăng từ `57.1 → 113.8`, tổng cost tăng gần gấp đôi `$0.000405 → $0.000792`) và latency tăng nhẹ thêm bước retrieval (~20 ms). Tuy nhiên accuracy tăng từ `4.3%` lên `100.0%`, khiến **cost / câu trả lời đúng giảm hơn 11 lần** (`$0.00040455 → $0.00003443`), chứng minh đánh đổi chi phí và latency nhỏ của RAG là hoàn toàn xứng đáng.

---

## 4. Observability stack (production)

- **Alert unit test (`promtool test rules /p/alert_rules_test.yml`):** `SUCCESS`.
- **Bảo mật `/metrics` qua Nginx:** `curl -i http://localhost:8080/metrics` trả `HTTP 404 Not Found` (Nginx chặn truy cập công khai `/metrics`, chỉ cho phép Prometheus nội bộ scrape).
- **Trả lời Exercise 7.4:**
  - `GET /metrics` qua cổng 8080 bị Nginx trả `404` để không lộ chỉ số vận hành nội bộ ra internet.
  - Input tokens/s lớn hơn output tokens/s vì prompt của agent v2 bao gồm `SYSTEM_PROMPT` + ngữ cảnh tài liệu retrieve được (RAG context) + câu hỏi, trong khi câu trả lời ngắn gọn hơn.
  - Panel *Requests/s theo instance* cho thấy Nginx chia tải tương đối đều giữa các instance agent thông qua Docker DNS round-robin.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với 2 alert cùng **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| --- | --- | --- | --- | --- |
| A | `MOCK_ERROR_RATE=0.2` (chạy đồng thời với C, tải Locust 30 users) | `AgentHighErrorRate` | ~100 giây (`pending` ở giây 38, `firing` ở giây 100 sau ngưỡng `for: 1m`) | Golden Signals — **Error rate** (đỏ) & **LLM calls ok/error** |
| C | `LLM_MODEL=mock-llm-large` (chạy đồng thời với A) | `LLMCostBurnRateHigh` | ~7–13 giây (vượt ngưỡng burn rate ngay khi tải lớn đổ vào model large đắt gấp ~16 lần) | **Cost USD/giờ** & **LLM p95 latency** |
| E | `AGENT_VERSION=v1` (phân tích lý thuyết từ Exercise 7.6) | Không có alert nào firing | Không firing | **Retrieval hit ratio** tụt về 0, **tokens/s** giảm, bảng **Agent version** đổi sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
Alert hạ tầng (error rate, latency, CPU, cost) đều "xanh" khi chất lượng câu trả lời suy giảm vì HTTP vẫn trả `200 OK` và thậm chí còn nhanh/rẻ hơn. Để phát hiện trong production cần:
1. **CI Eval Quality Gate** chạy `golden_dataset.jsonl` trước khi deploy (chặn PR/release nếu accuracy giảm hoặc có regression).
2. **Online evaluation & feedback metrics:** theo dõi tỉ lệ retrieval hit ratio (đặt alert khi hit ratio tụt mạnh), phản hồi 👍/👎 của người dùng, hoặc chạy **LLM-as-a-judge** trên mẫu traffic thật (vd 5% request) rồi xuất metric chất lượng sang Prometheus.

### 4.3 Debug bằng trace

Trace chậm nhất tìm được trong Jaeger:

- **`trace_id`:** `f9692a5a8e9998baa7cb0fcfb101bfb7`
- **Tổng thời gian:** `2001.3 ms`
- **Span chiếm nhiều thời gian nhất:** `chat mock-llm-large` (`1983.4 ms`, **99.1%** tổng thời gian; trong khi `agent.retrieve_context` chỉ mất `15.3 ms` = `0.8%`)
- **Dòng log JSON tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):**

```json
{"ts": "2026-11-25T08:16:07.518287+00:00", "level": "INFO", "service": "observable-agent", "instance": "d33f6f8f1095", "event": "llm_call", "trace_id": "f9692a5a8e9998baa7cb0fcfb101bfb7", "span_id": "54734e62cfe07bca", "request_id": "cb261beb5b79", "model": "mock-llm-large", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 0.000555, "llm_ms": 1983.2}
```

Trace lỗi đối chiếu kèm log JSON (`trace_id`: `4a86979db5101c0c949ba1d8d37d7d88`):

```json
{"ts": "2026-11-25T08:13:33.671839+00:00", "level": "INFO", "service": "observable-agent", "instance": "97524c3c5d1a", "event": "llm_error", "trace_id": "4a86979db5101c0c949ba1d8d37d7d88", "span_id": "b7c85a427e7f9a48", "request_id": "d061b34d69ad", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn dữ liệu: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` (số liệu endpoint `POST /ask`; dòng Aggregated gồm cả `GET /health` tương ứng là `65.25 RPS / p95 330 ms` và `66.23 RPS / p95 240 ms`).

| Số instance | RPS (`POST /ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 59.22 | 200 | 350 | 1700 | 68 / 7,085 (0.96%) |
| 3 | 60.33 | 190 | 250 | 1700 | 72 / 7,215 (1.00%) |

**Giải thích kết quả:**
Khi scale từ 1 lên 3 instance, **p95 giảm rõ rệt từ `350 ms` xuống `250 ms`** (-28.6%) nhờ giảm thời gian chờ hàng đợi CPU/event loop trên mỗi container (với giới hạn 0.5 CPU/container). Tuy nhiên **RPS chỉ tăng nhẹ (`59.22 → 60.33 req/s`)** và **p99 giữ nguyên ở `1700 ms`** vì:
1. Tải Locust cố định ở `100` users có thời gian nghỉ (wait time), nên tổng lượng request sinh ra bị chặn bởi tốc độ client và thời gian chờ I/O.
2. **Nút thắt chính nằm ở upstream LLM latency** (chiếm >90% thời gian mỗi request, với ~3% request chậm +1500 ms gây ra tail latency p99 = `1700 ms` và ~1% lỗi 503 ngẫu nhiên). Tăng số instance agent chỉ giải quyết nút thắt CPU/queue phía ứng dụng chứ không làm giảm độ trễ hay tỉ lệ lỗi của LLM upstream.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Tail latency quan trọng hơn average:** đặt SLO theo p95/p99 giúp phát hiện sớm nhóm người dùng chịu độ trễ cao mà trung bình che giấu.
  2. **Chất lượng cần eval tự động riêng biệt với observability hạ tầng:** metrics/alerts hạ tầng không phát hiện được câu trả lời sai (như khi tụt về v1), nên bắt buộc phải có golden dataset + CI quality gate + chỉ số `cost / câu đúng`.
  3. **Liên kết 3 trụ cột Metrics – Traces – Logs:** Grafana/Prometheus cho biết *có sự cố*, Jaeger trace chỉ ra chính xác *span gây chậm* (`chat mock-llm-large` chiếm 99.1%), còn `trace_id` trong JSON log cho phép truy vết ngược từng request cụ thể.
- **Nếu đưa agent lên production thật, sẽ thêm metric / alert:**
  - Metric & alert ở tầng **Load Balancer / Synthetic probe bên ngoài** (để bắt lỗi `502`/`504` mà metric bên trong agent không nhìn thấy).
  - Metric **Retrieval hit ratio** và **User feedback / online eval score** để cảnh báo sớm suy giảm chất lượng RAG.
  - Metric **Redis latency / error rate** và **Rate limit / Cost guard rejection rate (`429`, `402`)** để phát hiện tấn công lạm dụng hoặc sắp cạn ngân sách.
