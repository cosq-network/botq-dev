"""Phase 2 end-to-end smoke test against a running stack (nginx on :8080).

Covers: requirement baseline intake -> analysis -> submit -> approval loop with
segregation of duties, and the Work Item hierarchy with dependencies + circular rejection.
Exits non-zero on any failed assertion.
"""

import sys

import requests

BASE = "http://localhost:8080/api/v1"
ORG = "acme"
ADMIN = ("admin@acme.local", "S3curePass!")
REVIEWER = ("owner@acme.local", "OwnerPass123!")

_failures = []


def check(name, cond, detail=""):
    print(
        f"{'PASS' if cond else 'FAIL'}  {name}"
        + (f" :: {detail}" if detail and not cond else "")
    )
    if not cond:
        _failures.append(name)


def login(email, password):
    r = requests.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password, "organization": ORG},
    )
    r.raise_for_status()
    return r.json()["data"]["token"]


def H(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    admin = login(*ADMIN)
    reviewer = login(*REVIEWER)
    check("login admin + reviewer", bool(admin) and bool(reviewer))

    # fresh project
    key = "p2" + str(abs(hash(admin)) % 100000)
    pr = requests.post(
        f"{BASE}/projects",
        headers=H(admin),
        json={"name": "P2 Demo", "key": key, "default_branch": "main"},
    )
    project_id = pr.json()["data"]["id"]
    check("create project", pr.status_code == 201)

    content = {
        "goals": ["deliver safely"],
        "functional_specifications": ["approve before build"],
        "constraints": ["single VPS"],
        "acceptance_expectations": ["System must return 200 within 1 second"],
        "attachments": [],
        "repository_references": [],
    }
    br = requests.post(
        f"{BASE}/requirements/baselines",
        headers=H(admin),
        json={"project_id": project_id, "title": "P2 Intake", "content": content},
    )
    baseline = br.json()["data"]
    check(
        "create baseline (draft)",
        br.status_code == 201 and baseline["status"] == "draft",
    )

    analysis = requests.post(
        f"{BASE}/requirements/baselines/{baseline['id']}/analyze", headers=H(admin)
    )
    analysis_data = analysis.json().get("data", {})
    check(
        "analyze baseline",
        analysis.status_code == 201
        and analysis_data.get("summary", {}).get("blocking_count") == 0,
    )

    sr = requests.post(
        f"{BASE}/requirements/baselines/{baseline['id']}/submit", headers=H(admin)
    )
    check(
        "submit baseline",
        sr.status_code == 200 and sr.json()["data"]["status"] == "submitted",
    )

    ar = requests.post(
        f"{BASE}/requirements/baselines/{baseline['id']}/approve", headers=H(admin)
    )
    check(
        "author self-approval rejected (segregation of duties)",
        ar.status_code == 409 and ar.json()["error"]["code"] == "segregation_of_duties",
        detail=f"got {ar.status_code} {ar.text[:120]}",
    )

    ar2 = requests.post(
        f"{BASE}/requirements/baselines/{baseline['id']}/approve", headers=H(reviewer)
    )
    check(
        "reviewer approves -> status approved",
        ar2.status_code == 200 and ar2.json()["data"]["status"] == "approved",
    )

    hist = requests.get(
        f"{BASE}/approvals?artifact_type=requirement_baseline&artifact_id={baseline['id']}",
        headers=H(admin),
    ).json()["data"]
    check(
        "approval bound to version+hash",
        len(hist) == 1
        and hist[0]["artifact_version"] == 1
        and hist[0]["self_approval"] is False,
    )

    # Work item hierarchy under the approved baseline
    def mk(kind, title, parent=None):
        body = {
            "project_id": project_id,
            "kind": kind,
            "title": title,
            "source_baseline_id": baseline["id"],
            "is_derived": False,
        }
        if parent:
            body["parent_id"] = parent
        return requests.post(f"{BASE}/work-items", headers=H(reviewer), json=body)

    epic = mk("epic", "Platform Epic")
    feature = mk("feature", "Requirement gate", epic.json()["data"]["id"])
    story = mk("story", "Approve baseline", feature.json()["data"]["id"])
    task = mk("task", "Build approval UI", story.json()["data"]["id"])
    codes = [
        epic.json()["data"]["code"],
        feature.json()["data"]["code"],
        story.json()["data"]["code"],
        task.json()["data"]["code"],
    ]
    check(
        "build epic>feature>story>task hierarchy",
        all(r.status_code == 201 for r in (epic, feature, story, task)),
        detail=str(codes),
    )
    check(
        "identifiers are PROJECTKEY-<n>",
        codes
        == [
            f"{key.upper()}-1",
            f"{key.upper()}-2",
            f"{key.upper()}-3",
            f"{key.upper()}-4",
        ],
        detail=str(codes),
    )

    bad = mk("story", "orphan story (no parent)")
    check("story without parent rejected", bad.status_code == 422)

    dep = requests.post(
        f"{BASE}/work-items/{story.json()['data']['id']}/dependencies",
        headers=H(reviewer),
        json={"depends_on_id": feature.json()["data"]["id"]},
    )
    check("add dependency", dep.status_code == 200)
    cyc = requests.post(
        f"{BASE}/work-items/{feature.json()['data']['id']}/dependencies",
        headers=H(reviewer),
        json={"depends_on_id": story.json()["data"]["id"]},
    )
    check(
        "circular dependency rejected",
        cyc.status_code == 409 and cyc.json()["error"]["code"] == "circular_dependency",
    )

    tree = requests.get(
        f"{BASE}/work-items/tree?project_id={project_id}", headers=H(reviewer)
    ).json()["data"]
    check(
        "work item tree has single root", len(tree) == 1 and tree[0]["kind"] == "epic"
    )

    av = requests.get(f"{BASE}/audit/verify", headers=H(admin)).json()["data"]
    check("audit chain verified", av["verified"] is True, detail=str(av.get("failure")))

    print()
    if _failures:
        print(f"RESULT: Phase 2 demo FAILED -> {_failures}")
        return 1
    print("RESULT: Phase 2 demo PASSED (intake -> approval -> work items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
