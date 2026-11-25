"""
Production AI Agent — Part 6 Final Project.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Mỗi dòng log là 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("production_agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(JsonFormatter())
    logger.addHandler(_handler)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": {"event": event, **fields}})


_previous_sigterm = signal.getsignal(signal.SIGTERM)


def _on_sigterm(signum, frame):
    log_event("sigterm", signal=signum)
    if callable(_previous_sigterm):
        _previous_sigterm(signum, frame)


signal.signal(signal.SIGTERM, _on_sigterm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, port=settings.port)
    yield
    log_event("shutdown", environment=settings.environment)


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=ms,
            env=settings.environment,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_event("unhandled_error", level=logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = None


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn chạy."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi Redis sẵn sàng, 503 khi Redis không kết nối được."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)

    log_event(
        "ask_completed",
        user_id=body.user_id or "anonymous",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
    )
    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": round(cost, 6),
    }
