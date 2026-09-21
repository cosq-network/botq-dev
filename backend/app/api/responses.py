from flask import g, jsonify

from ..utils import new_uuid


def _correlation_id() -> str:
    return getattr(g, "correlation_id", None) or new_uuid().hex


def ok(data=None, message: str | None = None, status: int = 200):
    body = {"ok": True, "correlation_id": _correlation_id()}
    if message:
        body["message"] = message
    if data is not None:
        body["data"] = data
    return jsonify(body), status


def error_response(message: str, code: str, status: int, details=None):
    body = {
        "ok": False,
        "correlation_id": _correlation_id(),
        "error": {"code": code, "message": message},
    }
    if details:
        body["error"]["details"] = details
    return jsonify(body), status
