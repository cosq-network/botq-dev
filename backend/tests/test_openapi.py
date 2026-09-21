from app.api.openapi import _openapi_path


def test_openapi_json_documents_registered_api_routes(client, app):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.get_json()
    assert document["openapi"] == "3.0.3"
    assert "/api/v1/auth/login" in document["paths"]
    assert "/api/v1/projects/{project_id}" in document["paths"]
    assert "bearerAuth" in document["components"]["securitySchemes"]
    project_schema_ref = document["paths"]["/api/v1/projects"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    project_schema = document["components"]["schemas"][project_schema_ref.rsplit("/", 1)[-1]]
    assert "name" in project_schema["properties"]
    assert project_schema["properties"]["name"]["anyOf"][0]["type"] == "string"
    assert len(document["paths"]) >= 70

    documented_routes = {
        (path, method.upper())
        for path, operations in document["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    actual_routes = {
        (_openapi_path(rule.rule), method)
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/v1")
        for method in rule.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert actual_routes <= documented_routes


def test_swagger_ui_is_available(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui.css" in response.get_data(as_text=True)
    assert "Content-Security-Policy" in response.headers


def test_typed_dto_rejects_invalid_field_types(client):
    response = client.post("/api/v1/auth/login", json={"email": 42, "password": "secret"})

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"
