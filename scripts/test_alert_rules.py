"""Basic static validation for alert and scrape configuration."""
from pathlib import Path


def main() -> int:
    alerts = Path("ops/alerts.yml").read_text(encoding="utf-8")
    scrape = Path("ops/prometheus.yml").read_text(encoding="utf-8")
    required = ("BotqReadinessFailure", "BotqHttpErrorRate", "BotqAgentRunsFailing")
    if not all(item in alerts for item in required) or "/health/metrics/prometheus" not in scrape:
        raise SystemExit("alert or scrape configuration is incomplete")
    print("alert configuration baseline passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
