# Deployment Information — Day 14 (Agent Part 6)

> **Lưu ý:** Cập nhật `<YOUR-PUBLIC-URL>` bên dưới sau khi deploy thư mục `06-lab-complete/` lên Railway hoặc Render, và bổ sung 3 ảnh chụp (`screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`).

## Public URL
https://<YOUR-PUBLIC-URL>

## Platform
Railway / Render *(chọn nền tảng bạn đã deploy)*

## Environment Variables Set (trên nền tảng, không ghi vào code)
- `PORT` (tự động inject bởi nền tảng)
- `ENVIRONMENT=production`
- `REDIS_URL` (trỏ tới managed Redis service trên nền tảng)
- `AGENT_API_KEY` (đặt trên Dashboard / CLI, không commit vào git)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`

## Test Commands (CP6 Self-Test)

Đặt biến môi trường trước khi chạy (không để lộ `AGENT_API_KEY` khi chụp ảnh):

```bash
export BASE="https://<YOUR-PUBLIC-URL>"
export AGENT_API_KEY="<YOUR-API-KEY>"

# 1. Health check -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên cloud) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. POST /ask không có API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'

# 4. POST /ask có API key hợp lệ -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

Kiểm tra tự động kèm URL public bằng script chấm:

```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
