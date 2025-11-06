from __future__ import annotations
import os, time
from flask import Flask, jsonify
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException, BadRequest
from flask import request
from models.base import Base, engine
import models.entities  # noqa: F401
import models
from sqlalchemy import text
from models.scripts.replay_changes import seed_from_changes  # <-- NEW
from api import api_blueprint




def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
    DEBUG=False,                     # niente Werkzeug debugger HTML
    TESTING=False,
    PROPAGATE_EXCEPTIONS=False,      # lascia gestire agli handler
    JSON_SORT_KEYS=False,
)
    

    # Aspetta il DB con retry esponenziale (max ~30s)
    backoff = 0.5
    for attempt in range(10):
        try:
            with engine.begin() as conn:
                Base.metadata.create_all(bind=conn)
            break
        except OperationalError:
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)
    else:
        # ultimo tentativo fuori dal loop (fa raise se ancora giù)
        with engine.begin() as conn:
            Base.metadata.create_all(bind=conn)

    try:
        applied = seed_from_changes()
        if applied:
            app.logger.info("Applied %d change(s) from changes.json", applied)
        else:
            app.logger.info("No changes applied (changes.json empty or missing)")
    except Exception as e:
        # non bloccare l'avvio dell'API, logga l'errore
        app.logger.error("Replay changes failed: %s", e)


    @app.get("/health")
    def health():
        return jsonify(status="ok")

    app.register_blueprint(api_blueprint, url_prefix="/api")

    @app.errorhandler(HTTPException)
    def handle_http_exc(e: HTTPException):
    # errori 4xx/5xx di Flask/Werkzeug -> JSON
        payload = {
            "error": e.name,
            "message": e.description or e.name,
            "status": e.code,
            "path": request.path,
        }
        return jsonify(payload), e.code
    @app.errorhandler(Exception)
    def handle_unexpected_exc(e: Exception):
        # errori non gestiti -> 500 JSON, log completo nei log del container
        app.logger.exception("Unhandled exception")
        payload = {
            "error": "Internal Server Error",
            "message": "Unexpected error",
            "status": 500,
            "path": request.path,
        }
        return jsonify(payload), 500

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
