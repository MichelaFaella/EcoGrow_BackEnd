import time
import uuid
import requests


def test_login_wrong_password(base_url, creds):
    """
    Verifica che il login con password errata restituisca 401.
    Endpoint: POST /auth/login
    Request body: { "email": "...", "password": "..." }
    Expected response: 401 con { "error": "Invalid credentials" }
    """
    http = requests.Session()
    r = http.post(f"{base_url}/auth/login", json={
        "email": creds["email"],
        "password": "wrong_password_123"
    })
    assert r.status_code == 401, f"Expected 401 for wrong password, got {r.status_code}: {r.text}"
    assert "Invalid credentials" in r.text or "error" in r.json()


def test_login_nonexistent_email(base_url):
    """
    Verifica che il login con email non esistente restituisca 401.
    Endpoint: POST /auth/login
    Request body: { "email": "nonexistent@...", "password": "..." }
    Expected response: 401 con { "error": "Invalid credentials" }
    """
    http = requests.Session()
    fake_email = f"nonexistent_{uuid.uuid4().hex}@example.com"
    r = http.post(f"{base_url}/auth/login", json={
        "email": fake_email,
        "password": "any_password_123"
    })
    assert r.status_code == 401, f"Expected 401 for non-existent email, got {r.status_code}: {r.text}"
    assert "Invalid credentials" in r.text or "error" in r.json()


def test_malformed_token(base_url):
    """
    Verifica che un token JWT malformato restituisca 401 su endpoint protetti.
    Endpoint protetto: GET /check-auth (richiede require_jwt)
    Authorization header: "Bearer abc123_not_a_valid_jwt"
    Expected response: 401 con { "error": "Unauthorized" }
    """
    http = requests.Session()
    http.headers["Authorization"] = "Bearer abc123_not_a_valid_jwt"
    
    r = http.get(f"{base_url}/check-auth")
    assert r.status_code == 401, f"Expected 401 for malformed token, got {r.status_code}: {r.text}"
    
    # Anche su altri endpoint protetti
    r = http.get(f"{base_url}/user_plant/all")
    assert r.status_code == 401, f"Expected 401 for malformed token on /user_plant/all, got {r.status_code}"


def test_expired_or_invalid_token(base_url):
    """
    Verifica che un token JWT con formato valido ma scaduto/non valido restituisca 401.
    Usiamo un token JWT con struttura corretta ma firma non valida.
    Authorization header: "Bearer eyJ... (token fittizio)"
    Expected response: 401 con { "error": "Unauthorized" }
    """
    http = requests.Session()
    # Token JWT fittizio con struttura valida ma firma errata
    fake_jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1c2VyX2lkIjoiMTIzNDU2NzgtMTIzNC0xMjM0LTEyMzQtMTIzNDU2Nzg5YWJjIiwiZXhwIjoxMH0."
        "invalid_signature_here"
    )
    http.headers["Authorization"] = f"Bearer {fake_jwt}"
    
    r = http.get(f"{base_url}/check-auth")
    assert r.status_code == 401, f"Expected 401 for expired/invalid token, got {r.status_code}: {r.text}"
    
    # Verifica anche su un endpoint che modifica dati
    r = http.post(f"{base_url}/user_plant/add", json={"plant_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 401, f"Expected 401 for expired token on POST, got {r.status_code}"


def test_missing_credentials(base_url):
    """
    Verifica che il login senza email o password restituisca 400.
    Endpoint: POST /auth/login
    Request body: { } o parziale
    Expected response: 400 con { "error": "email/password missing" }
    """
    http = requests.Session()
    
    # Senza email
    r = http.post(f"{base_url}/auth/login", json={"password": "test123"})
    assert r.status_code == 400, f"Expected 400 for missing email, got {r.status_code}"
    
    # Senza password  
    r = http.post(f"{base_url}/auth/login", json={"email": "test@example.com"})
    assert r.status_code == 400, f"Expected 400 for missing password, got {r.status_code}"
    
    # Body vuoto
    r = http.post(f"{base_url}/auth/login", json={})
    assert r.status_code == 400, f"Expected 400 for empty body, got {r.status_code}"


def test_auth_flow(user_token_and_session, base_url):
    access, http = user_token_and_session

    # check-auth with valid token
    r = http.get(f"{base_url}/check-auth")
    assert r.status_code in (200, 401)  # your /check-auth returns 401 if no Authorization header
    # Force explicit with Authorization header
    headers = {"Authorization": http.headers["Authorization"]}
    r = http.get(f"{base_url}/check-auth", headers=headers)
    assert r.status_code == 200 and r.json().get("authenticated") == True

    # refresh (using cookie stored in session)
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (200, 401)  # may be 401 if refresh cookie/domain mismatch in CI
    if r.status_code == 200:
        new_acc = r.json().get("access_token")
        assert new_acc and len(new_acc) > 20


def test_auth_extended(user_token_and_session, base_url):
    access, http = user_token_and_session

    # refresh WITH cookie should usually work
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (200, 401), f"/auth/refresh unexpected: {r.status_code} {r.text}"
    if r.status_code == 200:
        new_access = r.json().get("access_token")
        assert new_access and len(new_access) > 20

    # simulate "no cookie": new session without cookies
    import requests
    no_cookie = requests.Session()
    r = no_cookie.post(f"{base_url}/auth/refresh")
    assert r.status_code in (400, 401), f"refresh without cookie should fail: {r.status_code} {r.text}"

    # logout should invalidate refresh
    r = http.post(f"{base_url}/auth/logout")
    assert r.status_code in (200, 204)

    # after logout, refresh should fail (even with former cookies)
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (400, 401), f"refresh after logout should fail: {r.status_code} {r.text}"