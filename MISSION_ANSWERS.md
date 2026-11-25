# Day 14 Lab — Mission Answers

> **Học viên:** Khuat Tien Minh  
> **Môi trường thực hiện:** WSL2 Ubuntu (`os.name == 'posix'`, Python 3.14.4), Docker 29.9.3, Docker Compose v5.7.0

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong source code (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub (nhất là repo public), secret bị lộ ngay lập tức và còn tồn tại trong lịch sử commit.
2. **Hardcode cấu hình và bật chế độ debug (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` không đọc từ biến môi trường, không thể tách cấu hình giữa dev / staging / production mà không sửa code.
3. **Dùng `print()` thay cho structured logging và in thẳng secret ra log (dòng 33–34, 38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa làm lộ API key trong log, vừa không có timestamp, log level hay định dạng JSON để log aggregator (Loki, Datadog) tìm kiếm và phân tích.
4. **Không có Health Check / Readiness endpoint (dòng 42–43):** Thiếu `GET /health` và `GET /ready`, nên cloud platform hoặc load balancer không biết container có còn sống hay đã sẵn sàng nhận traffic chưa để tự động restart hoặc ngắt route.
5. **Bind cứng `host="localhost"`, `port=8000` và bật `reload=True` (dòng 49–54):**
   - `host="localhost"` khiến app không nhận được kết nối từ bên ngoài container.
   - `port=8000` cố định không đọc biến môi trường `PORT` do Railway/Render/Cloud Run cấp.
   - `reload=True` chỉ dùng lúc phát triển, gây tốn tài nguyên và mất ổn định ở production.
6. **Không có Graceful Shutdown:** Khi nhận `SIGTERM`, process dừng đột ngột, cắt ngang các request đang xử lý (in-flight requests).

### Exercise 1.2: Kết quả chạy và gọi bản `develop`

Bản `develop` nhận `question` qua query parameter (`POST /ask?question=Hello`):

```text
$ curl -sS -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:40:59 GMT
server: uvicorn
content-length: 95
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Kết quả gọi bản `production` (`/health`, `/ready`, `/ask`):

```text
GET /health -> {"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:41:02.112071+00:00"}
GET /ready  -> {"ready":true}
POST /ask   -> {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Tại sao quan trọng? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True` trong `app.py` (dòng 17–22) | Đọc toàn bộ từ biến môi trường qua `Settings` (`os.getenv(...)`) trong `config.py` (dòng 15–35) và fail-fast qua `validate()` (dòng 37–46) | Tuân thủ 12-Factor App: cùng một artifact/image chạy được trên dev/staging/prod, không lộ secret trong git. |
| **Health & Readiness** | Không có | Có `GET /health` (liveness, dòng 135–149) và `GET /ready` (readiness trả 503 khi chưa sẵn sàng, dòng 152–161) | Orchestrator/cloud biết khi nào cần restart container (liveness) và khi nào được phép đẩy traffic vào (readiness). |
| **Logging** | Dùng `print()` dạng text và log cả `OPENAI_API_KEY` (dòng 33–38) | Structured JSON logging (`logging.basicConfig` + `json.dumps`, dòng 28–32, 111–122), tuyệt đối không log secret | Dễ parse, filter, truy vết lỗi trên hệ thống tập trung và bảo vệ thông tin nhạy cảm. |
| **Shutdown** | Dừng đột ngột, không xử lý `SIGTERM` | Dùng `lifespan` (dòng 39–67) đặt `is_ready = False`, chờ request hoàn thành và đăng ký `signal.SIGTERM` (dòng 180–189) | Tránh rớt request của người dùng khi deploy bản mới hoặc scale down container. |
| **Network binding & Reload** | `host="localhost"`, `port=8000`, `reload=True` (dòng 51–53) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `PORT`), `reload=settings.debug` (dòng 194–199) | Bắt buộc bind `0.0.0.0` và đọc `PORT` động để chạy trong Docker và các cloud PaaS. |
| **CORS & Input validation** | Không có CORS, nhận `question` qua query | Có `CORSMiddleware` cấu hình `ALLOWED_ORIGINS` (dòng 77–82), nhận JSON body và trả 422 nếu thiếu `question` (dòng 103–108) | Kiểm soát nguồn truy cập và chuẩn hóa contract REST API. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (bản Python đầy đủ gồm compiler, công cụ hệ thống và thư viện Debian đầy đủ, dung lượng lớn ~1 GB+).
2. **Working directory là gì?** `/app` (đặt bằng lệnh `WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`?** Để tận dụng **Docker layer cache**. File `requirements.txt` ít thay đổi hơn source code; khi chỉ sửa code (`app.py`), Docker tái sử dụng lại layer `RUN pip install -r requirements.txt` đã cache thay vì cài lại toàn bộ thư viện từ đầu, giúp build nhanh hơn rất nhiều.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `ENTRYPOINT` định nghĩa tiến trình chính cố định của container (khó bị ghi đè trừ khi dùng `--entrypoint`).
   - `CMD` cung cấp lệnh mặc định (hoặc tham số mặc định cho `ENTRYPOINT`) và dễ dàng bị ghi đè khi truyền thêm đối số ở cuối lệnh `docker run <image> <override_cmd>`.

### Exercise 2.2: Kết quả build & gọi container `my-agent:develop`

Build từ gốc repo bằng `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .` và chạy `docker run -p 8000:8000 my-agent:develop`:

```text
$ curl -sS -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 07:43:29 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & so sánh kích thước image (đo thực tế)

- **Stage 1 (`builder` — `python:3.11-slim`):** Cài `gcc`, `libpq-dev` để biên dịch các package phụ thuộc C/native, sau đó `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime` — `python:3.11-slim`):** Tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng source code cần chạy, cấu hình `USER appuser` và `HEALTHCHECK`.
- **Vì sao image nhỏ hơn?** Dùng base `slim` thay vì full `python:3.11`, đồng thời loại bỏ hoàn toàn các build tools (`gcc`, `libpq-dev`, apt cache) chỉ tồn tại ở stage `builder`, giúp image cuối vừa gọn vừa giảm bề mặt tấn công bảo mật.

**Kết quả đo thực tế bằng `docker images my-agent` và `docker image inspect`:**

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:develop    bfafe52fe6de       1.67GB          426MB
my-agent:advanced   38768e2eacc3        240MB         57.4MB
```

- **Develop (`my-agent:develop`):** `1,667,775,754` bytes (**1,667.8 MB** / 1.67 GB)
- **Production (`my-agent:advanced`):** `239,811,317` bytes (**239.8 MB** / 240 MB)
- **Chênh lệch:** Giảm **1,427.96 MB**, tương đương nhỏ hơn **85.62%** so với bản develop.

### Exercise 2.4: Kiến trúc Docker Compose stack (`02-docker/production/docker-compose.yml`) và kết quả test qua Nginx

```text
Client (HTTP :80)
       │
       ▼
┌─────────────────────┐
│   nginx (:80/:443)  │  (Reverse proxy & Load balancer, security headers)
└──────────┬──────────┘
           │ network: internal
           ▼
┌─────────────────────┐
│    agent (:8000)    │  (FastAPI + uvicorn --workers 2, depends_on redis & qdrant healthy)
└────┬───────────┬────┘
     │           │
     ▼           ▼
┌─────────┐ ┌──────────┐
│  redis  │ │  qdrant  │
│ (:6379) │ │ (:6333)  │
│ volume: │ │ volume:  │
│redis_dat│ │qdrant_dat│
└─────────┘ └──────────┘
```

- 4 service được khởi chạy trong bridge network `internal`: `nginx`, `agent`, `redis`, `qdrant`. Chỉ `nginx` mở cổng ra host (`80`, `443`); các service còn lại giao tiếp nội bộ qua Docker DNS (`redis:6379`, `qdrant:6333`, `agent:8000`).

**Kết quả test thực tế qua Nginx (`http://localhost`):**

```text
$ curl -sS -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":0.7,"version":"2.0.0","timestamp":"2026-11-25T07:45:40.588856"}

$ curl -sS -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 (`06-lab-complete/`) lên Render

- **Platform:** Render (Web Service Docker + Redis)
- **Public URL:** https://k5-l3-day14-khuattienminh-2a202603616.onrender.com
- **Kết quả kiểm thử trực tiếp:**
  - `GET /health` → `200` (`{"status":"ok","environment":"production"}`)
  - `GET /ready` → `200` (`{"status":"ready"}`)
  - `POST /ask` (thiếu `X-API-Key`) → `401` (`{"detail":"Invalid or missing API key"}`)
  - `POST /ask` (có `X-API-Key` đặt trên Render Dashboard) → `200`
  - `python check_production_ready.py --public-url "https://k5-l3-day14-khuattienminh-2a202603616.onrender.com"` → **`PASS 12/12` (44/44 checks passed)**
- **Screenshots:** [screenshots/dashboard.png](screenshots/dashboard.png), [screenshots/running.png](screenshots/running.png), [screenshots/test.png](screenshots/test.png)
- **Chi tiết cấu hình & lệnh test:** xem [DEPLOYMENT.md](DEPLOYMENT.md)

### So sánh `railway.toml` vs `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` (Blueprint IaC) |
| --- | --- | --- |
| **Định dạng & phạm vi** | TOML, cấu hình build & deploy cho **1 service** cụ thể (Dockerfile/Nixpacks, healthcheck, restart policy). | YAML, khai báo **Infrastructure as Code cho toàn bộ stack** (nhiều service web + database/Redis, plan, region, envVars). |
| **Khai báo biến môi trường & secrets** | Thường thiết lập riêng trên Railway Dashboard hoặc qua `railway variables set` (không khai báo trong `railway.toml`). | Khai báo trực tiếp danh sách `envVars` trong file; hỗ trợ `generateValue: true` (Render tự sinh secret) hoặc `sync: false` (nhập tay trên dashboard, không commit secret). |
| **Managed Redis / Add-ons** | Thêm qua Dashboard/CLI và nối biến `${{Redis.REDIS_URL}}`. | Có thể khai báo trực tiếp resource Redis trong cùng Blueprint `render.yaml`. |
| **Điểm chung** | Đều hỗ trợ build từ `Dockerfile`, cấu hình healthcheck `/health`, và tự động inject biến `PORT` khi chạy container. |

### Exercise 3.3: Mô tả CI/CD pipeline GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Pipeline trong `cloudbuild.yaml` kết hợp cấu hình `service.yaml` chạy tự động qua 4 bước tuần tự khi push lên nhánh `main`:
1. **Test (`test`):** Dùng container `python:3.11-slim` cài dependencies và chạy `pytest tests/ -v`; nếu test fail thì dừng pipeline ngay.
2. **Build (`build`):** Dùng `cloud-builders/docker` build Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`), tận dụng `--cache-from` để tăng tốc build.
3. **Push (`push`):** Đẩy toàn bộ tag image vừa build lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`deploy`):** Gọi `gcloud run deploy ai-agent` triển khai image theo `$COMMIT_SHA` lên vùng `asia-southeast1` với cấu hình `min-instances=1` (tránh cold start), `max-instances=10`, giới hạn CPU/RAM (`1 CPU / 512Mi`), `livenessProbe` (`/health`), `startupProbe` (`/ready`) và inject secret an toàn từ **Google Secret Manager** (`--set-secrets` / `secretKeyRef`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop`)

- **Kiểm tra ở đâu:** Trong dependency `verify_api_key()` đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` và inject vào `POST /ask` bằng `Depends(verify_api_key)`.
- **Nếu thiếu / sai key:** Thiếu key trả `401 Unauthorized`; sai key trong bản develop trả `403 Forbidden` (ở Part 6 chuẩn hóa cả thiếu và sai key đều trả `401`).
- **Cách rotate key an toàn:** Lưu key trong biến môi trường / Secret Manager; hỗ trợ danh sách nhiều key hợp lệ tạm thời (key cũ + key mới) trong thời gian chuyển đổi, cập nhật client sang key mới rồi thu hồi key cũ mà không gây downtime.

**Output thực tế (`AGENT_API_KEY=secret-key-123`):**

```text
# Không có key -> 401
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Có key -> 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production`)

- **Thuật toán Rate Limiter (`rate_limiter.py`):** **Sliding Window** lưu danh sách timestamp (`deque`) trong cửa sổ `window_seconds=60` cho từng `user_id`; mỗi request mới sẽ loại bỏ các timestamp cũ hơn `now - 60`, kiểm tra `len(window) >= max_requests` để trả `429 Too Many Requests` kèm header `Retry-After` và `X-RateLimit-*`.
- **Giới hạn:** Tài khoản `student` (role `user`) bị giới hạn **10 req/phút** (`rate_limiter_user`), còn `teacher` (role `admin`) được **100 req/phút** (`rate_limiter_admin`) — phân tách theo `role` trong payload JWT.

**Output thực tế (đã che JWT token):**

```text
# Lấy JWT từ POST /auth/token (student / demo123)
Got JWT token (masked): eyJhbGciOiJI...<REDACTED>

# Gọi /ask lần 1 với JWT -> 200
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Vòng lặp gọi liên tiếp:
Request 2..10 -> HTTP 200
Request 11    -> HTTP 429

# Chi tiết response 429:
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795592831
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách làm Cost Guard & lý do cần cả Rate Limit lẫn Cost Guard

- **Cách làm Cost Guard:** Lưu tổng chi phí LLM theo ngày/tháng trên **Redis** (key dạng `cost:daily:YYYY-MM-DD` hoặc `budget:{user_id}:{YYYY-MM}` có đặt TTL tự hết hạn). **Trước** khi gọi LLM, kiểm tra chi phí hiện tại >= ngân sách thì chặn ngay với `HTTP 402 Payment Required` (và cảnh báo khi đạt 80%). **Sau** khi gọi LLM, tính chi phí thực tế theo số input/output tokens và cộng dồn nguyên tử bằng `INCRBYFLOAT`.
- **Tại sao cần cả hai:** **Rate limit** bảo vệ *tốc độ* (chống spam/DDoS làm quá tải server), nhưng một user gọi chậm rãi với prompt cực dài hoặc dùng model đắt tiền vẫn có thể đốt sạch ngân sách. **Cost guard** bảo vệ *tiền* (giới hạn tổng chi tiêu USD), giúp tránh hóa đơn LLM bất ngờ ngay cả khi traffic nằm dưới ngưỡng rate limit.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check, Readiness & Graceful Shutdown (`05-scaling-reliability/develop`)

- **Phân biệt Liveness (`/health`) vs Readiness (`/ready`):**
  - `GET /health` (Liveness): kiểm tra process còn sống không. Luôn trả `200` khi process hoạt động bình thường (kể cả khi Redis tạm mất kết nối), tránh việc orchestrator restart vòng lặp vô ích.
  - `GET /ready` (Readiness): kiểm tra instance đã sẵn sàng nhận traffic chưa (đã load xong, kết nối được Redis/DB, chưa ở trạng thái shutdown). Nếu trả `503`, load balancer tạm ngừng route traffic vào instance đó mà không kill container.
- **Kết quả test thực tế (`/health`, `/ready` và `kill -SIGTERM` khi đang có request):**

```text
GET /health -> {"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:46:13.626570+00:00","checks":{"memory":{"status":"ok","used_percent":15.0}}}
GET /ready  -> {"ready":true,"in_flight_requests":1}

# Gửi request POST /ask?question=Long%20task rồi gửi ngay SIGTERM:
In-flight response: {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
Shutdown log:
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1700]
INFO Received signal 15 — uvicorn will handle graceful shutdown
```

### Exercise 5.3–5.5: Stateless Design & Load Balancing với 3 instances (`05-scaling-reliability/production`)

- **Tại sao state trong RAM hỏng khi scale:** Khi chạy 3 instance sau Nginx load balancer, request 1 có thể vào `agent-1` còn request 2 vào `agent-2`. Nếu lịch sử hội thoại hoặc bộ đếm rate limit nằm trong RAM của từng process, `agent-2` sẽ không thấy dữ liệu của `agent-1` và toàn bộ session sẽ bị mất khi container restart. Chuyển state ra **Redis** dùng chung giúp mọi instance đều stateless.
- **Kết quả chạy thực tế `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py` (cổng 8080, endpoint `POST /chat`):**

```text
Session ID: f668a69d-20cb-413a-9cf8-67be8e745842

Request 1: [instance-592765]  Q: What is Docker?
Request 2: [instance-21dc4b]  Q: Why do we need containers?
Request 3: [instance-592765]  Q: What is Kubernetes?
Request 4: [instance-d8682c]  Q: How does load balancing work?
Request 5: [instance-21dc4b]  Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-d8682c', 'instance-592765', 'instance-21dc4b'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** Cả 5 request thuộc cùng một `session_id` được Nginx phân phối đều sang cả 3 container agent khác nhau, nhưng khi đọc lại `/chat/{session_id}/history`, toàn bộ 10 tin nhắn (5 user + 5 assistant) vẫn đầy đủ vì dữ liệu được lưu tập trung trong Redis.

---

## Part 6: Final Project — Kết quả `check_production_ready.py` (`06-lab-complete/`)

Chạy bản đầy đủ (có Docker) trong WSL2 Ubuntu (`os.name == 'posix'`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chỉ số đo thực tế từ script kiểm tra:
- **Docker image size:** `297 MB` (< 500 MB), thời gian build `50s`.
- **Rate limiting:** trả `429` sau đúng 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`), sau khi restart agent vẫn trả `429` (state lưu bền vững trong Redis).
- **Readiness khi Redis down:** `/ready` trả `503`, trong khi `/health` vẫn trả `200`.
- **Structured logging:** 17 dòng log JSON hợp lệ.
- **Graceful shutdown:** `SIGTERM` lúc đang xử lý request → request vẫn trả `200`, process thoát với `exit code 0`; `docker stop` thoát với `exit code 0` trong `1.1s` (< 10s).

---

## AI Log (theo quy định trong `RULES.md`)

1. **Thiết lập môi trường WSL2 & kiểm tra Docker:**
   - *Hỏi gì:* Hỗ trợ kiểm tra môi trường WSL2 Ubuntu (`os.name == 'posix'`, Docker Desktop WSL Integration) và tạo virtualenv Python không cần quyền root (`ensurepip` chưa cài sẵn).
   - *Nhận gì:* Phát hiện Docker Desktop chưa bật WSL integration cho distro `Ubuntu` (distro mặc định là `docker-desktop`), hướng dẫn bật tích hợp trong Settings → Resources → WSL Integration và tạo venv bằng `python3 -m venv --without-pip` kết hợp `get-pip.py`.
   - *Tự sửa & tự kiểm tra:* Bật WSL Integration trong Docker Desktop, xác nhận lại `docker info` trả về Docker Server 29.9.3 và `docker compose` v5.7.0 trong Ubuntu.
2. **Triển khai `06-lab-complete/` (Part 6 Final Project):**
   - *Hỏi gì:* Hoàn thiện các file TODO (`app/config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) theo đúng hợp đồng chấm điểm của `06-lab-complete/README.md`.
   - *Nhận gì:* Code triển khai sliding-window rate limiter bằng Redis Sorted Set (`ZREMRANGEBYSCORE`/`ZCARD`/`ZADD`/`EXPIRE`), cost guard bằng `INCRBYFLOAT`, JSON logger tách biệt khỏi uvicorn, SIGTERM handler gọi lại handler gốc của uvicorn, multi-stage `Dockerfile` non-root với `PYTHONUSERBASE`.
   - *Tự sửa & tự kiểm tra:* Chạy `python check_production_ready.py` bản đầy đủ trong WSL2 Ubuntu có Docker, đạt `PASS 12/12` (43/43 checks passed, image 297 MB, `docker stop` 1.1s).
3. **Part 1, 2, 4, 5 và Part 7 Benchmark & Observability:**
   - *Hỏi gì:* Chạy tự động hóa các bài test theo lưu ý K5 (cổng 8080 cho Part 5, `-p` cho Docker Compose, `POST /auth/token` với `student`/`demo123` cho Part 4, thêm metric `agent_question_length_chars`, sửa `KNOWLEDGE_BASE` cho 2 câu `security-02` và `scaling-03`, chạy load test/eval/Locust/chaos alerts).
   - *Nhận gì:* Các script chạy kiểm chứng thực tế trên máy local + tổng hợp số liệu từ JSON/CSV/Jaeger/Prometheus thật (không sửa `check_production_ready.py` và `golden_dataset.jsonl`, không bịa số liệu).
   - *Tự sửa & tự kiểm tra:* Đối chiếu toàn bộ số liệu trong `MISSION_ANSWERS.md` và `BENCHMARK_REPORT.md` khớp 100% với output thực tế và các file trong `reports/`, `benchmark-results/`.
