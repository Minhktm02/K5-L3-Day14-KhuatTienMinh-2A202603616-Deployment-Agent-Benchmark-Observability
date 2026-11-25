# Deployment Information — Day 14 (Agent Part 6)

## Public URL
https://k5-l3-day14-khuattienminh-2a202603616.onrender.com

## Platform
Render (Web Service chạy Docker từ `06-lab-complete/Dockerfile` + Managed Redis)

## Environment Variables Set (cấu hình trên Render Dashboard, không ghi trong code)
- `PORT` (tự động inject bởi Render)
- `ENVIRONMENT=production`
- `REDIS_URL` (kết nối tới Redis instance trên Render)
- `AGENT_API_KEY` (đặt trên Render Dashboard, không commit vào git)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`

## Test Commands (CP6 Self-Test)

Đặt biến môi trường trước khi chạy (chỉ in mã HTTP, không lộ `AGENT_API_KEY`):

```bash
export BASE="https://k5-l3-day14-khuattienminh-2a202603616.onrender.com"
export AGENT_API_KEY="<YOUR-RENDER-AGENT-API-KEY>"

# 1. Health check -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên Render) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. POST /ask không có API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'

# 4. POST /ask có API key hợp lệ -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Kết quả kiểm thử thực tế
- `GET /health` → `HTTP 200` (`{"status":"ok","environment":"production"}`)
- `GET /ready` → `HTTP 200` (`{"status":"ready"}`)
- `POST /ask` (không có `X-API-Key`) → `HTTP 401` (`{"detail":"Invalid or missing API key"}`)
- `POST /ask` (có `X-API-Key` hợp lệ) → `HTTP 200` (xem ảnh `screenshots/test.png`)
- `python check_production_ready.py --public-url "https://k5-l3-day14-khuattienminh-2a202603616.onrender.com"` → **PASS 12/12 (44/44 checks passed)**

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
