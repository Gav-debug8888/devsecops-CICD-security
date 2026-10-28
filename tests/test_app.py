import pytest

from app import create_app

TOKEN = "test-token-not-a-real-secret"


@pytest.fixture()
def client(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, DB_PATH=str(tmp_path / "test.db"), API_TOKEN=TOKEN)
    return app.test_client()


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]


def test_create_requires_token(client):
    r = client.post("/items", json={"name": "widget", "quantity": 1})
    assert r.status_code == 401


def test_create_and_get_item(client):
    r = client.post("/items", json={"name": "widget", "quantity": 3}, headers=auth())
    assert r.status_code == 201
    item_id = r.get_json()["id"]
    assert client.get(f"/items/{item_id}").get_json()["quantity"] == 3


@pytest.mark.parametrize("payload", [
    {"name": "", "quantity": 1},
    {"name": "x" * 101, "quantity": 1},
    {"name": "ok", "quantity": -1},
    {"name": "ok", "quantity": "5"},
    {"name": "ok", "quantity": True},
    ["not", "an", "object"],
])
def test_input_validation(client, payload):
    assert client.post("/items", json=payload, headers=auth()).status_code == 400


def test_search_is_not_sql_injectable(client):
    client.post("/items", json={"name": "widget", "quantity": 1}, headers=auth())
    r = client.get("/items", query_string={"q": "' OR '1'='1"})
    assert r.status_code == 200
    assert r.get_json() == []


def test_delete(client):
    item_id = client.post("/items", json={"name": "w", "quantity": 1}, headers=auth()).get_json()["id"]
    assert client.delete(f"/items/{item_id}").status_code == 401
    assert client.delete(f"/items/{item_id}", headers=auth()).status_code == 204
    assert client.get(f"/items/{item_id}").status_code == 404
