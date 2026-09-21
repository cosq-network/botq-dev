"""Verify Redis-backed rate limiting is shared across API app instances."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app import create_app
from app.config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    _flush_rate_limit_keys(args.redis_url)

    class RedisRateLimitConfig(Config):
        RATE_LIMIT_ENABLED = True
        RATE_LIMIT_PER_MINUTE = args.limit
        RATE_LIMIT_BACKEND = "redis"
        REDIS_URL = args.redis_url
        TESTING = False

    apps = [create_app(RedisRateLimitConfig), create_app(RedisRateLimitConfig)]
    responses = []
    for index in range(args.limit + 1):
        app = apps[index % len(apps)]
        response = app.test_client().get("/health/live", environ_base={"REMOTE_ADDR": "10.9.0.7"})
        responses.append({"instance": index % len(apps), "status_code": response.status_code})

    expected = [200] * args.limit + [429]
    ok = [item["status_code"] for item in responses] == expected
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "redis",
        "limit": args.limit,
        "instances": len(apps),
        "responses": responses,
        "expected": expected,
        "ok": ok,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": ok, "output": str(output)}, sort_keys=True))
    return 0 if ok else 1


def _flush_rate_limit_keys(redis_url: str) -> None:
    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    for key in client.scan_iter("botq:ratelimit:*"):
        client.delete(key)


if __name__ == "__main__":
    raise SystemExit(main())
