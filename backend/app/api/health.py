from flask import Blueprint, Response, current_app

from ..api.responses import ok
from ..extensions import db
from ..observability import metrics

hp = Blueprint("health", __name__)

LIVENESS = {"status": "ok"}


@hp.get("/health/live")
def liveness():
    metrics().set_gauge("health_live", 1)
    return ok(LIVENESS)


@hp.get("/health/ready")
def readiness_probe():
    db_ok = True
    detail = "ok"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        # Do not expose driver messages: they may contain connection strings,
        # hostnames, usernames, or other deployment-sensitive information.
        detail = type(exc).__name__
    metrics().set_gauge("health_ready", 1 if db_ok else 0)
    return ok(
        {
            "status": "ready" if db_ok else "not_ready",
            "database": "up" if db_ok else "down",
            "detail": detail,
            "environment": current_app.config["ENVIRONMENT"],
        },
        status=200 if db_ok else 503,
    )


@hp.get("/health/metrics")
def metrics_probe():
    return ok(metrics().snapshot())


@hp.get("/health/metrics/prometheus")
def prometheus_metrics_probe():
    return Response(metrics().prometheus(), mimetype="text/plain; version=0.0.4")
