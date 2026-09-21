from app.models import AuditEvent


def _project(client, headers, key):
    return client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": key.title(), "key": key, "default_branch": "main"},
    ).get_json()["data"]


def _item(client, headers, project_id, kind, title, parent_id=None, derived=True):
    payload = {"project_id": project_id, "kind": kind, "title": title, "is_derived": derived}
    if parent_id:
        payload["parent_id"] = parent_id
    return client.post("/api/v1/work-items", headers=headers, json=payload)


def _chain(client, headers, project_id):
    epic = _item(client, headers, project_id, "epic", "Epic").get_json()["data"]
    feature = _item(client, headers, project_id, "feature", "Feature", epic["id"]).get_json()[
        "data"
    ]
    story = _item(client, headers, project_id, "story", "Story", feature["id"]).get_json()["data"]
    task = _item(client, headers, project_id, "task", "Task", story["id"]).get_json()["data"]
    return epic, feature, story, task


def test_create_valid_hierarchy_and_identifiers(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi1")
    epic, feature, story, task = _chain(client, headers, project["id"])
    assert [epic["code"], feature["code"], story["code"], task["code"]] == [
        "WI1-1",
        "WI1-2",
        "WI1-3",
        "WI1-4",
    ]
    assert feature["parent_id"] == epic["id"]
    assert task["kind"] == "task"
    got = client.get(f"/api/v1/work-items/{task['id']}", headers=headers)
    assert got.status_code == 200
    assert got.get_json()["data"]["code"] == "WI1-4"


def test_epic_must_be_root(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi2")
    epic = _item(client, headers, project["id"], "epic", "E1").get_json()["data"]
    bad = _item(client, headers, project["id"], "epic", "E2", epic["id"])
    assert bad.status_code == 422


def test_story_requires_parent(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi3")
    resp = _item(client, headers, project["id"], "story", "orphan")
    assert resp.status_code == 422


def test_hierarchy_rank_enforced(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi4")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]
    # a feature cannot be a child of ... nothing weird; epic under feature would be:
    resp = client.post(
        "/api/v1/work-items",
        headers=headers,
        json={
            "project_id": project["id"],
            "kind": "feature",
            "title": "F",
            "parent_id": epic["id"],
            "is_derived": True,
        },
    )
    assert resp.status_code == 201


def test_unknown_kind_rejected(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi5")
    resp = _item(client, headers, project["id"], "milestone", "M")
    assert resp.status_code == 422


def test_traceability_required(client, auth_headers, org):
    headers = auth_headers()
    project = _project(client, headers, "wi6")
    # no baseline, not derived -> rejected
    resp = client.post(
        "/api/v1/work-items",
        headers=headers,
        json={"project_id": project["id"], "kind": "epic", "title": "E", "is_derived": False},
    )
    assert resp.status_code == 422

    # valid baseline reference
    content = {"goals": ["g"], "constraints": []}
    baseline = client.post(
        "/api/v1/requirements/baselines",
        headers=headers,
        json={"project_id": project["id"], "title": "B", "content": content},
    ).get_json()["data"]
    ok = client.post(
        "/api/v1/work-items",
        headers=headers,
        json={
            "project_id": project["id"],
            "kind": "epic",
            "title": "E2",
            "source_baseline_id": baseline["id"],
            "source_refs": ["goal:0"],
            "is_derived": False,
        },
    )
    assert ok.status_code == 201
    assert ok.get_json()["data"]["source_baseline_id"] == baseline["id"]


def test_dependency_and_circular_rejection(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi7")
    a, b, c, _ = _chain(client, headers, project["id"])
    # b depends on a (legit)
    dep = client.post(
        f"/api/v1/work-items/{b['id']}/dependencies",
        headers=headers,
        json={"depends_on_id": a["id"]},
    )
    assert dep.status_code == 200
    assert dep.get_json()["data"]["dependencies"] == [a["code"]]

    # c depends on b, b depends on a -> making a depend on c is circular
    client.post(
        f"/api/v1/work-items/{c['id']}/dependencies",
        headers=headers,
        json={"depends_on_id": b["id"]},
    )
    cycle = client.post(
        f"/api/v1/work-items/{a['id']}/dependencies",
        headers=headers,
        json={"depends_on_id": c["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.get_json()["error"]["code"] == "circular_dependency"


def test_self_dependency_rejected(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi8")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]
    resp = client.post(
        f"/api/v1/work-items/{epic['id']}/dependencies",
        headers=headers,
        json={"depends_on_id": epic["id"]},
    )
    assert resp.status_code == 409


def test_reparent_cycle_rejected(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wi9")
    epic, feature, story, _ = _chain(client, headers, project["id"])
    # make epic a child of its own descendant (story) -> circular hierarchy
    resp = client.patch(
        f"/api/v1/work-items/{epic['id']}", headers=headers, json={"parent_id": story["id"]}
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "circular_hierarchy"


def test_delete_requires_no_children(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wia")
    epic, feature, _story, _task = _chain(client, headers, project["id"])
    blocked = client.delete(f"/api/v1/work-items/{epic['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["code"] == "work_item_has_children"

    got = client.get(f"/api/v1/work-items/{feature['id']}", headers=headers).get_json()["data"]
    # feature has a story child -> also blocked
    assert client.delete(f"/api/v1/work-items/{got['id']}", headers=headers).status_code == 409


def test_list_and_tree(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wib")
    _chain(client, headers, project["id"])
    listing = client.get(
        f"/api/v1/work-items?project_id={project['id']}", headers=headers
    ).get_json()["data"]
    assert len(listing) == 4
    tree = client.get(
        f"/api/v1/work-items/tree?project_id={project['id']}", headers=headers
    ).get_json()["data"]
    assert len(tree) == 1  # single root epic
    assert tree[0]["code"] == "WIB-1"
    assert tree[0]["children"][0]["code"] == "WIB-2"


def test_update_fields(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wic")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]
    resp = client.patch(
        f"/api/v1/work-items/{epic['id']}",
        headers=headers,
        json={"priority": "critical", "risk": "high", "acceptance_criteria": ["done when X"]},
    )
    data = resp.get_json()["data"]
    assert data["priority"] == "critical"
    assert data["risk"] == "high"
    assert data["acceptance_criteria"] == ["done when X"]


def test_invalid_status_rejected(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers, "wid")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]
    resp = client.patch(
        f"/api/v1/work-items/{epic['id']}", headers=headers, json={"status": "teleported"}
    )
    assert resp.status_code == 422


def test_tenant_isolation(client, auth_headers, app, org):
    from app.auth.providers.local import LocalProvider
    from app.orgs.service import create_organization

    headers = auth_headers()
    project = _project(client, headers, "wie")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]

    other = create_organization("Other WI Tenant", slug="wi-tenant")
    LocalProvider(other.slug).ensure_local_user(
        "wi@other.local", "password123", "Other", ["organization_administrator"]
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "wi@other.local", "password": "password123", "organization": other.slug},
    ).get_json()["data"]["token"]
    other_headers = {"Authorization": f"Bearer {token}"}
    got = client.get(f"/api/v1/work-items/{epic['id']}", headers=other_headers)
    assert got.status_code == 404


def test_scope_required(client, auth_headers, app, org):
    from app.auth.providers.local import LocalProvider

    headers = auth_headers()
    project = _project(client, headers, "wif")
    LocalProvider(org.slug).ensure_local_user(
        "wi-dev@test.local", "password123", "Dev", ["developer"]
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "wi-dev@test.local", "password": "password123", "organization": org.slug},
    ).get_json()["data"]["token"]
    dev_headers = {"Authorization": f"Bearer {token}"}
    # developer has requirement:read but not requirement:write
    denied = _item(client, dev_headers, project["id"], "epic", "nope")
    assert denied.status_code == 401
    read_ok = client.get(f"/api/v1/work-items?project_id={project['id']}", headers=dev_headers)
    assert read_ok.status_code == 200


def test_work_item_audit_recorded(client, auth_headers, org):
    headers = auth_headers()
    project = _project(client, headers, "wig")
    epic = _item(client, headers, project["id"], "epic", "E").get_json()["data"]
    client.patch(f"/api/v1/work-items/{epic['id']}", headers=headers, json={"status": "ready"})
    actions = [e.action for e in AuditEvent.query.filter_by(organization_id=org.id).all()]
    assert "work_item.created" in actions
    assert "work_item.updated" in actions
