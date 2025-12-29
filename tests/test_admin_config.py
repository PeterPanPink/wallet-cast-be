import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin.config import YamlConvertParams, router
from app.shared.api.utils import verify_api_key


@pytest.fixture(scope="module")
def test_app():
    app = FastAPI()
    # Override API key dependency globally for tests
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture(scope="module")
def client(test_app):
    return TestClient(test_app)


def test_yaml_example_invalid_code_returns_failure(client):
    r = client.get("/api/v1/admin/yaml/example/unknown")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data.get("errcode") == "E_INVALID_PARAMS"
    assert isinstance(data.get("errmesg"), str) and data["errmesg"]


def test_yaml_convert_invalid_schema_returns_failure(client):
    yaml_text = """
invalid: true
""".strip()
    body = YamlConvertParams(yaml=yaml_text, ssid="sess1").model_dump()
    r = client.post("/api/v1/admin/yaml/convert/default", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data.get("errcode") == "E_CONFIG_FORMAT_INVALID"
    assert isinstance(data.get("errmesg"), str) and data["errmesg"]


def test_yaml_convert_malformed_yaml_returns_failure(client):
    body = YamlConvertParams(yaml="::bad_yaml::", ssid="sess2").model_dump()
    r = client.post("/api/v1/admin/yaml/convert/default", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data.get("errcode") == "E_CONFIG_FORMAT_INVALID"
    assert isinstance(data.get("errmesg"), str) and data["errmesg"]


def test_yaml_convert_unknown_code_returns_failure(client):
    body = YamlConvertParams(yaml="enable: true", ssid="sess5").model_dump()
    r = client.post("/api/v1/admin/yaml/convert/unknown", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data.get("errcode") == "E_CONFIG_CODE_NOT_FOUND"
    assert isinstance(data.get("errmesg"), str) and data["errmesg"]
