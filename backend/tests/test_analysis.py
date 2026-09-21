from app.models import WorkItem
from app.requirements.analysis import (
    AnalysisProviderError,
    FallbackRequirementAnalyzer,
    configured_analyzer,
    parse_provider_result,
)


def _content(**overrides):
    content = {
        "goals": ["Deliver secure access"],
        "functional_specifications": ["Users must log in"],
        "constraints": [],
        "acceptance_expectations": ["System must return 200 within 1 second"],
        "attachments": [],
        "repository_references": [],
    }
    content.update(overrides)
    return content


def _project(client, headers, key="analyze"):
    return client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": key.title(), "key": key, "default_branch": "main"},
    ).get_json()["data"]


def _baseline(client, headers, project_id, content=None, title="Analysis"):
    return client.post(
        "/api/v1/requirements/baselines",
        headers=headers,
        json={
            "project_id": project_id,
            "title": title,
            "content": content or _content(),
        },
    ).get_json()["data"]


def _login(client, email, org_slug):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123", "organization": org_slug},
    ).get_json()["data"]["token"]


def test_analysis_is_version_bound_and_generates_reviewable_proposals(client, auth_headers):
    headers = auth_headers()
    project = _project(client, headers)
    baseline = _baseline(client, headers, project["id"])

    response = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/analyze", headers=headers
    )
    assert response.status_code == 201
    analysis = response.get_json()["data"]
    assert analysis["provider"] == "rules"
    assert analysis["baseline_version"] == 1
    assert analysis["baseline_hash"] == baseline["content_hash"]
    assert analysis["summary"]["blocking_count"] == 0
    assert {proposal["kind"] for proposal in analysis["proposed_work_items"]} == {
        "epic",
        "feature",
        "test_case",
    }

    applied = client.post(
        f"/api/v1/requirements/analyses/{analysis['id']}/work-items", headers=headers
    )
    assert applied.status_code == 201
    assert len(applied.get_json()["data"]) == 3
    assert WorkItem.query.filter_by(source_analysis_id=analysis["id"]).count() == 3

    repeated = client.post(
        f"/api/v1/requirements/analyses/{analysis['id']}/work-items", headers=headers
    )
    assert repeated.status_code == 200
    assert len(repeated.get_json()["data"]) == 3


def test_blocking_findings_prevent_approval_until_resolved(client, auth_headers, org):
    headers = auth_headers()
    project = _project(client, headers, key="block")
    baseline = _baseline(
        client,
        headers,
        project["id"],
        content=_content(acceptance_expectations=[]),
        title="Blocking analysis",
    )
    analysis = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/analyze", headers=headers
    ).get_json()["data"]
    assert analysis["summary"]["blocking_count"] == 1
    finding = next(item for item in analysis["findings"] if item["blocking"])

    client.post(f"/api/v1/requirements/baselines/{baseline['id']}/submit", headers=headers)
    from app.auth.providers.local import LocalProvider

    LocalProvider(org.slug).ensure_local_user(
        "analysis-reviewer@test.local", "password123", "Analysis Reviewer", ["product_owner"]
    )
    reviewer_headers = {
        "Authorization": f"Bearer {_login(client, 'analysis-reviewer@test.local', org.slug)}"
    }
    blocked = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["code"] == "blocking_requirement_findings"

    resolved = client.post(
        f"/api/v1/requirements/analyses/{analysis['id']}/findings/{finding['id']}/resolve",
        headers=headers,
        json={"reason": "Added acceptance criteria during review"},
    )
    assert resolved.status_code == 200
    approved = client.post(
        f"/api/v1/requirements/baselines/{baseline['id']}/approve", headers=reviewer_headers
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["status"] == "approved"


def test_provider_output_is_schema_validated():
    parsed = parse_provider_result(
        {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"findings": [], "proposed_work_items": []}\n```'
                    }
                }
            ]
        }
    )
    assert parsed.findings == []
    assert parsed.proposed_work_items == []

    parsed = parse_provider_result(
        {
            "choices": [
                {"message": {"content": '```json\n{"findings": [], "proposed_work_items": []}'}}
            ]
        }
    )
    assert parsed.findings == []
    assert parsed.proposed_work_items == []

    try:
        parse_provider_result({"output": "not json"})
    except AnalysisProviderError:
        pass
    else:
        raise AssertionError("invalid provider output must be rejected")
    try:
        parse_provider_result({})
    except AnalysisProviderError:
        pass
    else:
        raise AssertionError("missing provider output fields must be rejected")


def test_provider_object_source_refs_are_canonicalized():
    parsed = parse_provider_result(
        {
            "findings": [],
            "proposed_work_items": [
                {
                    "ref": "feature-1",
                    "kind": "feature",
                    "title": "Secure login",
                    "description": "Users can log in.",
                    "acceptance_criteria": ["Login succeeds for valid credentials"],
                    "priority": "urgent",
                    "risk": "critical",
                    "source_refs": [{"field": "functional_specifications", "index": 0}],
                }
            ],
        }
    )
    assert parsed.proposed_work_items[0]["source_refs"] == [
        '{"field":"functional_specifications","index":0}'
    ]
    assert parsed.proposed_work_items[0]["priority"] == "critical"
    assert parsed.proposed_work_items[0]["risk"] == "high"


def test_managed_provider_fallback_is_explicitly_configurable():
    analyzer = configured_analyzer(
        {
            "REQUIREMENT_ANALYSIS_PROVIDER": "heroku,runpod",
            "REQUIREMENT_ANALYSIS_TIMEOUT_SECONDS": 5,
            "HEROKU_INFERENCE_BASE_URL": "https://us.inference.heroku.com",
            "HEROKU_INFERENCE_KEY": "heroku-test-key",
            "HEROKU_INFERENCE_MODEL": "test-model",
            "RUNPOD_API_KEY": "runpod-test-key",
            "RUNPOD_ENDPOINT_ID": "endpoint-test",
            "RUNPOD_INFERENCE_URL": "https://runpod.test/runsync",
        }
    )
    assert isinstance(analyzer, FallbackRequirementAnalyzer)
    assert analyzer.provider == "heroku+runpod"
    assert analyzer.analyzers[0].url.endswith("/v1/chat/completions")
    assert analyzer.analyzers[1].url == "https://runpod.test/runsync"
