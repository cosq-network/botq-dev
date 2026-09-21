"""Small, dependency-free observability and request-protection primitives."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from flask import current_app, g, request

from .errors import ApiError


class MetricsRegistry:
    """Process-local metrics suitable for health checks and smoke diagnostics.

    Production deployments should scrape or forward these values from each
    web/worker process. Values are deliberately aggregate and contain no
    request headers, payloads, tokens, or tenant identifiers.
    """

    def __init__(self, sample_limit: int = 1000):
        self._lock = threading.Lock()
        self._counters = defaultdict(int)
        self._gauges = {}
        self._samples = defaultdict(lambda: deque(maxlen=sample_limit))

    def increment(self, name: str, amount: int = 1, labels: dict | None = None) -> None:
        with self._lock:
            self._counters[_metric_key(name, labels)] += amount

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        with self._lock:
            self._samples[_metric_key(name, labels)].append(round(value, 3))

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        with self._lock:
            self._gauges[_metric_key(name, labels)] = round(value, 3)

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            observations = {}
            for key, values in self._samples.items():
                ordered = sorted(values)
                observations[key] = {
                    "count": len(values),
                    "sum": round(sum(values), 3),
                    "max": max(values) if values else 0,
                    "p95": _percentile(ordered, 0.95),
                }
        return {"counters": counters, "gauges": gauges, "observations": observations}

    def prometheus(self) -> str:
        snapshot = self.snapshot()
        lines = []
        for key, value in snapshot["counters"].items():
            name, labels = _parse_metric_key(key)
            lines.append(f"{name}{_prometheus_labels(labels)} {value}")
        for key, value in snapshot["gauges"].items():
            name, labels = _parse_metric_key(key)
            lines.append(f"{name}{_prometheus_labels(labels)} {value}")
        for key, values in snapshot["observations"].items():
            name, labels = _parse_metric_key(key)
            label_text = _prometheus_labels(labels)
            for suffix in ("count", "sum", "max", "p95"):
                lines.append(f"{name}_{suffix}{label_text} {values[suffix]}")
        return "\n".join(lines) + ("\n" if lines else "")


class RequestRateLimiter:
    """Fixed-window in-memory limiter for a single process.

    This is a safety baseline, not a substitute for a shared edge limiter in
    a horizontally scaled production deployment.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, limit: int, now: int | None = None) -> tuple[bool, int]:
        now = now or int(time.time())
        window = now // 60
        with self._lock:
            previous_window, count = self._windows.get(key, (window, 0))
            if previous_window != window:
                count = 0
            count += 1
            self._windows[key] = (window, count)
        return count <= limit, max(1, 60 - (now % 60))


class RedisRateLimiter:
    """Shared fixed-window limiter. Connection failures fail closed."""

    def __init__(self, url: str):
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - dependency is deployed with production extras
            raise RuntimeError("Redis rate limiting requires the redis package") from exc
        self.client = redis.Redis.from_url(url, decode_responses=True)

    def allow(self, key: str, limit: int, now: int | None = None) -> tuple[bool, int]:
        now = now or int(time.time())
        retry_after = max(1, 60 - (now % 60))
        bucket = f"botq:ratelimit:{now // 60}:{key}"
        try:
            count = self.client.incr(bucket)
            if count == 1:
                self.client.expire(bucket, retry_after + 1)
        except Exception as exc:
            raise ApiError("Shared rate limiter is unavailable", code="rate_limiter_unavailable", status=503) from exc
        return count <= limit, retry_after


def initialize(app) -> None:
    app.extensions["metrics"] = MetricsRegistry()
    backend = str(app.config.get("RATE_LIMIT_BACKEND", "memory")).lower()
    if backend == "redis":
        url = app.config.get("REDIS_URL", "")
        if not url:
            raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        app.extensions["rate_limiter"] = RedisRateLimiter(url)
    elif backend == "memory":
        app.extensions["rate_limiter"] = RequestRateLimiter()
    else:
        raise RuntimeError("RATE_LIMIT_BACKEND must be memory or redis")


def metrics() -> MetricsRegistry:
    return current_app.extensions["metrics"]


def before_request() -> None:
    g.request_started = time.perf_counter()
    if not current_app.config.get("RATE_LIMIT_ENABLED", False) or current_app.config.get(
        "TESTING", False
    ):
        return
    route = request.endpoint or request.path
    key = f"{request.remote_addr or 'unknown'}:{route}"
    allowed, retry_after = current_app.extensions["rate_limiter"].allow(
        key, current_app.config["RATE_LIMIT_PER_MINUTE"]
    )
    if not allowed:
        g.rate_limit_retry_after = retry_after
        raise ApiError(
            "Rate limit exceeded",
            code="rate_limited",
            status=429,
            details={"retry_after_seconds": retry_after},
        )


def after_request(response):
    started = getattr(g, "request_started", None)
    duration_ms = (time.perf_counter() - started) * 1000 if started else 0
    route = request.url_rule.rule if request.url_rule else request.path
    labels = {"method": request.method, "route": route, "status": str(response.status_code)}
    metrics().increment("http_requests_total", labels=labels)
    metrics().observe("http_request_duration_ms", duration_ms, labels={"route": route})
    response.headers["X-Correlation-ID"] = getattr(g, "correlation_id", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if current_app.config.get("ENVIRONMENT", "").lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if getattr(g, "rate_limit_retry_after", None):
        response.headers["Retry-After"] = str(g.rate_limit_retry_after)
    current_app.logger.info(
        "request_completed event=request_completed correlation_id=%s method=%s path=%s status=%s duration_ms=%.3f",
        getattr(g, "correlation_id", ""),
        request.method,
        route,
        response.status_code,
        duration_ms,
    )
    return response


def _metric_key(name: str, labels: dict | None) -> str:
    if not labels:
        return name
    suffix = ",".join(f"{key}={labels[key]}" for key in sorted(labels))
    return f"{name}{{{suffix}}}"


def _parse_metric_key(key: str) -> tuple[str, dict[str, str]]:
    if "{" not in key:
        return key, {}
    name, raw_labels = key[:-1].split("{", 1)
    labels = {}
    for item in raw_labels.split(","):
        label, value = item.split("=", 1)
        labels[label] = value
    return name, labels


def _prometheus_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    escaped = []
    for key, value in sorted(labels.items()):
        safe = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped.append(f'{key}="{safe}"')
    return "{" + ",".join(escaped) + "}"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, int((len(values) - 1) * percentile)))
    return values[index]
