"""Measure non-streaming health/API latency against a running instance."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import mean
from urllib.error import URLError
from urllib.request import Request, urlopen


def benchmark(base_url: str, endpoint: str, iterations: int, timeout: float, concurrency: int = 1) -> dict:
    url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
    durations = []
    errors = []
    def request_once(_):
        started = time.perf_counter()
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "botq-phase6-benchmark"}),
                timeout=timeout,
            ) as response:
                response.read()
                return None if response.status == 200 else f"HTTP {response.status}", (time.perf_counter() - started) * 1000
        except (OSError, URLError) as exc:
            return type(exc).__name__, (time.perf_counter() - started) * 1000
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for error, duration in pool.map(request_once, range(iterations)):
            if error:
                errors.append(error)
            durations.append(duration)
    ordered = sorted(durations)
    p95 = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
    return {
        "url": url,
        "iterations": iterations,
        "concurrency": concurrency,
        "errors": errors,
        "error_count": len(errors),
        "latency_ms": {
            "mean": round(mean(durations), 3),
            "p95": round(p95, 3),
            "max": round(max(durations), 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url", default=os.environ.get("BOTQ_BENCHMARK_URL", "http://127.0.0.1:5000")
    )
    parser.add_argument("--endpoint", default="/health/ready")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.iterations < 1 or args.concurrency < 1:
        parser.error("--iterations and --concurrency must be positive")
    report = benchmark(args.url, args.endpoint, args.iterations, args.timeout, args.concurrency)
    report["target_p95_ms"] = args.max_p95_ms
    report["passed"] = (
        report["error_count"] == 0 and report["latency_ms"]["p95"] <= args.max_p95_ms
    )
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{'PASS' if report['passed'] else 'FAIL'} {report['url']}")
        print(
            f"p95={report['latency_ms']['p95']}ms target={args.max_p95_ms}ms errors={report['error_count']}"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
