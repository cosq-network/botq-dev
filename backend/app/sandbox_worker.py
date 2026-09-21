import logging
import signal
import time

from . import create_app

log = logging.getLogger("botq.worker")

app = create_app()


def _run_cycle() -> None:
    with app.app_context():
        from .extensions import db

        db.session.execute(db.text("SELECT 1"))
        from .sandbox.readiness import build_readiness_report

        report = build_readiness_report()
        log.info(
            "worker cycle ok=%s missing=%s",
            report["mandatory_ok"],
            report["missing_mandatory"],
        )
        from .planning.worker import AgentRunWorker

        processed = AgentRunWorker(app).process_once()
        if processed:
            log.info("processed one durable agent run")
        db.session.remove()


STOP = False


def _stop(signum, frame):
    global STOP
    STOP = True


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    interval = float(app.config.get("AGENT_WORKER_POLL_SECONDS", 30))
    log.info("sandbox worker starting (interval=%ss)", interval)
    while not STOP:
        try:
            _run_cycle()
        except Exception as exc:
            log.error("worker cycle failed: %s", exc)
            time.sleep(5)
        else:
            time.sleep(interval)
    log.info("sandbox worker stopping")


if __name__ == "__main__":
    main()
