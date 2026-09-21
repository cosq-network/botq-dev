"""Run the repeatable HTTP portion of the BotQ pilot HAT checklist."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time

import requests


def csrf(session: requests.Session, path: str) -> str:
    response = session.get(session.base_url + path, timeout=15)
    response.raise_for_status()
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text)
    if not match:
        match = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', response.text)
    if not match:
        raise RuntimeError(f"No CSRF token found on {path}")
    return html.unescape(match.group(1))


def post_form(session: requests.Session, path: str, data: dict) -> requests.Response:
    response = session.post(session.base_url + path, data=data, timeout=15)
    response.raise_for_status()
    return response


def run(base_url: str) -> dict:
    base_url = base_url.rstrip("/")
    timestamp = str(int(time.time()))
    email = f"hat.{timestamp}@example.com"
    password = "PilotPassword!2026"
    results = []

    register_session = requests.Session()
    register_session.base_url = base_url
    token = csrf(register_session, "/register")
    response = post_form(
        register_session,
        "/register",
        {
            "csrf_token": token,
            "email": email,
            "password": password,
            "password_confirmation": password,
        },
    )
    results.append(
        {
            "criterion": "valid registration",
            "passed": "Registration complete" in response.text,
        }
    )

    duplicate_session = requests.Session()
    duplicate_session.base_url = base_url
    token = csrf(duplicate_session, "/register")
    response = post_form(
        duplicate_session,
        "/register",
        {
            "csrf_token": token,
            "email": email,
            "password": password,
            "password_confirmation": password,
        },
    )
    results.append(
        {
            "criterion": "duplicate registration rejected",
            "passed": "already exists" in response.text,
        }
    )

    mismatch_session = requests.Session()
    mismatch_session.base_url = base_url
    token = csrf(mismatch_session, "/register")
    response = post_form(
        mismatch_session,
        "/register",
        {
            "csrf_token": token,
            "email": f"mismatch.{timestamp}@example.com",
            "password": password,
            "password_confirmation": "DifferentPassword!2026",
        },
    )
    results.append(
        {
            "criterion": "password mismatch rejected",
            "passed": "Passwords must match" in response.text,
        }
    )

    auth_session = requests.Session()
    auth_session.base_url = base_url
    token = csrf(auth_session, "/login")
    response = post_form(
        auth_session,
        "/login",
        {"csrf_token": token, "email": email, "password": password},
    )
    dashboard = auth_session.get(base_url + "/dashboard", timeout=15)
    results.append(
        {
            "criterion": "valid login reaches dashboard",
            "passed": dashboard.status_code == 200
            and "Protected area" in dashboard.text,
        }
    )

    logout_token = csrf(auth_session, "/dashboard")
    logged_out = post_form(auth_session, "/logout", {"csrf_token": logout_token})
    results.append(
        {
            "criterion": "logout invalidates session",
            "passed": "logged out" in logged_out.text.lower()
            and auth_session.get(base_url + "/dashboard", timeout=15).url.endswith(
                "/login"
            ),
        }
    )

    invalid_session = requests.Session()
    invalid_session.base_url = base_url
    for attempt in range(1, 7):
        token = csrf(invalid_session, "/login")
        response = post_form(
            invalid_session,
            "/login",
            {
                "csrf_token": token,
                "email": f"unknown.{timestamp}@example.com",
                "password": "WrongPassword!2026",
            },
        )
        if attempt < 6 and "Invalid email or password" not in response.text:
            raise RuntimeError(
                f"invalid login attempt {attempt} did not return the safe error"
            )
    results.append(
        {
            "criterion": "sixth failed login rate-limited",
            "passed": "Too many failed attempts" in response.text,
        }
    )
    return {
        "base_url": base_url,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
        "passed": all(item["passed"] for item in results),
        "manual_review_required": True,
        "manual_review_scope": [
            "keyboard-only",
            "screen reader",
            "200% zoom/reflow",
            "contrast",
            "reduced motion",
            "error recovery",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        report = run(args.url)
    except (OSError, requests.RequestException, RuntimeError) as exc:
        print(f"HAT failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
