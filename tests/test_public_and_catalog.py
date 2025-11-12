# tests/test_public_and_catalog.py
import uuid

def _root(base_url: str) -> str:
    # base_url = http://localhost:8000/api
    return base_url.rsplit("/api", 1)[0]

def test_public_and_catalog(user_token_and_session, base_url):
    access, http = user_token_and_session

    # /ping (public)
    r = http.get(f"{base_url}/ping")
    assert r.status_code == 200 and r.json().get("ping") == "pong"

    # /check-auth: senza header il tuo backend può rispondere 200 o 401
    r = http.get(f"{base_url}/check-auth", headers={})
    assert r.status_code in (200, 401)

    # /check-auth: con Authorization header (ereditato dalla sessione) → 200
    r = http.get(f"{base_url}/check-auth")
    assert r.status_code == 200 and r.json().get("authenticated") is True

    # families e catalogo
    r = http.get(f"{base_url}/family/all")
    assert r.status_code == 200 and isinstance(r.json(), list)

    r = http.get(f"{base_url}/plants/all")
    assert r.status_code == 200 and isinstance(r.json(), list)

    # filtri
    r = http.get(f"{base_url}/plants/by-size/medium")
    assert r.status_code in (200, 400)  # 400 se size non ammesso, 200 altrimenti

    r = http.get(f"{base_url}/plants/by-use/ornamental")
    assert r.status_code == 200

def test_public_and_catalog_extended(user_token_and_session, base_url):
    access, http = user_token_and_session

    # /check-auth senza header con nuova Session (nessun cookie/headers)
    import requests
    tmp = requests.Session()
    r = tmp.get(f"{base_url}/check-auth")
    assert r.status_code in (200, 401)

    # /health sulla root app (accetta {ok: true} o {status: "ok"})
    r = http.get(f"{_root(base_url)}/health")
    assert r.status_code == 200 and (
        r.json().get("ok") is True or r.json().get("status") == "ok"
    )
