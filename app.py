"""Inventory API: a small, secure Flask service that the CI/CD security gate protects.

The app is deliberately simple so the pipeline is the focus. It still follows
secure defaults: parameterised SQL, input validation, no debug mode, secrets
from the environment and security headers on every response.
"""
import logging
import os
import sqlite3

from flask import Flask, abort, g, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inventory-api")

DB_PATH = os.environ.get("DB_PATH", "inventory.db")
API_TOKEN = os.environ.get("API_TOKEN")  # required for write operations
MAX_NAME_LEN = 100


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config.get("DB_PATH", DB_PATH))
            g.db.row_factory = sqlite3.Row
            g.db.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity >= 0))"
            )
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def require_token():
        token = app.config.get("API_TOKEN", API_TOKEN)
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token or supplied != token:
            log.warning("unauthorised write attempt from %s", request.remote_addr)
            abort(401)

    def validate_item(data):
        if not isinstance(data, dict):
            abort(400, description="JSON object required")
        name, qty = data.get("name"), data.get("quantity")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= MAX_NAME_LEN:
            abort(400, description=f"name must be 1-{MAX_NAME_LEN} characters")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            abort(400, description="quantity must be a non-negative integer")
        return name.strip(), qty

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(404)
    def handle_error(err):
        return jsonify(error=err.description if err.code == 400 else err.name), err.code

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/items")
    def list_items():
        q = request.args.get("q", "")[:MAX_NAME_LEN]
        rows = get_db().execute(
            "SELECT id, name, quantity FROM items WHERE name LIKE ? ORDER BY id", (f"%{q}%",)
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    # DEMO ONLY - deliberately vulnerable route to prove the security gate blocks it.
    # User input is concatenated straight into SQL (CWE-89), e.g. ?name=' OR '1'='1
    @app.get("/items/lookup")
    def lookup_item():
        name = request.args.get("name", "")
        query = "SELECT id, name, quantity FROM items WHERE name = '" + name + "'"
        rows = get_db().execute(query).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/items/<int:item_id>")
    def get_item(item_id: int):
        row = get_db().execute(
            "SELECT id, name, quantity FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            abort(404)
        return jsonify(dict(row))

    @app.post("/items")
    def create_item():
        require_token()
        name, qty = validate_item(request.get_json(silent=True))
        db = get_db()
        cur = db.execute("INSERT INTO items (name, quantity) VALUES (?, ?)", (name, qty))
        db.commit()
        return jsonify(id=cur.lastrowid, name=name, quantity=qty), 201

    @app.delete("/items/<int:item_id>")
    def delete_item(item_id: int):
        require_token()
        db = get_db()
        cur = db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        db.commit()
        if cur.rowcount == 0:
            abort(404)
        return "", 204

    return app


app = create_app()

if __name__ == "__main__":
    # Local development only. The container runs gunicorn (see Dockerfile).
    app.run(host="127.0.0.1", port=8000, debug=False)
