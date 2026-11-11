"""Restaurant Management API application factory."""
import logging
import os

from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .db import init_schema
from .util import ApiError

API_PREFIX = "/api/v1"


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE_URL=os.environ.get("DATABASE_URL", "sqlite:///restaurant.db"),
        TOKEN_TTL_HOURS=int(os.environ.get("TOKEN_TTL_HOURS", "12")),
        ALLOW_REGISTRATION=os.environ.get("ALLOW_REGISTRATION", "true").lower() == "true",
        SEED_NEW_RESTAURANTS=os.environ.get("SEED_NEW_RESTAURANTS", "true").lower() == "true",
        FORCE_HTTPS=os.environ.get("FORCE_HTTPS", "false").lower() == "true",
        MAX_CONTENT_LENGTH=1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY must be set (>= 32 characters). Generate one with: "
                           "python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    init_schema(app.config["DATABASE_URL"])

    from .routes import auth, billing, dashboard, kitchen, menu, orders, settings, staff, tables

    for module in (auth, menu, tables, orders, kitchen, billing, staff, settings, dashboard):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def enforce_https():
        if app.config["FORCE_HTTPS"] and request.headers.get("X-Forwarded-Proto", "https") != "https":
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    @app.after_request
    def finish(resp):
        conn = g.get("db")
        if conn is not None:
            conn.commit() if resp.status_code < 400 else conn.rollback()
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        if app.config["FORCE_HTTPS"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def error_response(status, code, message, details=None):
        payload = {"error": {"code": code, "message": message}}
        if details:
            payload["error"]["details"] = details
        return jsonify(payload), status

    @app.errorhandler(ApiError)
    def on_api_error(e):
        return error_response(e.status, e.code, e.message, e.details)

    @app.errorhandler(HTTPException)
    def on_http_error(e):
        return error_response(e.code, e.name.lower().replace(" ", "_"), e.description)

    @app.errorhandler(Exception)
    def on_unexpected(e):
        app.logger.exception("Unhandled error")
        return error_response(500, "internal_error", "An unexpected error occurred")

    @app.get("/health")
    def health():
        from .db import db
        db().one("SELECT 1 AS ok")
        return jsonify(status="ok")

    spec_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "openapi.yaml")

    @app.get(API_PREFIX + "/openapi.yaml")
    def openapi():
        with open(spec_path, encoding="utf-8") as fh:
            return Response(fh.read(), mimetype="application/yaml")

    @app.get("/api/docs")
    def docs():
        return Response(
            '<!doctype html><html><head><title>Restaurant API docs</title>'
            '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">'
            '</head><body><div id="ui"></div>'
            '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>'
            '<script>SwaggerUIBundle({url:"' + API_PREFIX + '/openapi.yaml",dom_id:"#ui"})</script>'
            '</body></html>', mimetype="text/html")

    @app.get("/")
    def web_home():
        return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"), "index.html")

    @app.get("/web/<path:filename>")
    def web_assets(filename):
        return send_from_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"), filename)

    return app
