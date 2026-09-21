"""Create deterministic users for the Dockerized API E2E suite."""

import os

from app import create_app
from app.auth.providers.local import LocalProvider


def main() -> None:
    app = create_app()
    with app.app_context():
        org = os.environ.get("BOTQ_E2E_ORG", "acme")
        password = os.environ.get("BOTQ_E2E_PASSWORD", "E2ePass!2026")
        LocalProvider(org).ensure_local_user(
            os.environ.get("BOTQ_E2E_ADMIN_EMAIL", "admin@acme.local"),
            password,
            "E2E Administrator",
            ["organization_administrator"],
        )
        LocalProvider(org).ensure_local_user(
            os.environ.get("BOTQ_E2E_REVIEWER_EMAIL", "reviewer@acme.local"),
            password,
            "E2E Reviewer",
            ["organization_administrator"],
        )
        print(f"Seeded E2E users in organization {org}")


if __name__ == "__main__":
    main()
