import os, uuid, pytest, requests

@pytest.fixture(scope="session")
def base_url():
    return os.environ.get("BASE", "http://localhost:8000/api").rstrip("/")

@pytest.fixture(scope="session")
def creds():
    email = os.environ.get("EMAIL") or f"tester_{uuid.uuid4().hex[:10]}@example.com"
    password = os.environ.get("PASS", "secret123")
    return {"email": email, "password": password}

@pytest.fixture(scope="session")
def http():
    s = requests.Session()
    # NON impostare Content-Type qui: requests lo gestisce da solo
    return s

def _expect_status(resp, code, msg=""):
    assert resp.status_code == code, f"{msg} expected {code}, got {resp.status_code}, body={resp.text}"

@pytest.fixture(scope="session")
def user_token_and_session(http, base_url, creds):
    # create user (best effort)
    http.post(f"{base_url}/user/add", json={
        "email": creds["email"], "password": creds["password"],
        "first_name": "Test", "last_name": "User"
    })

    # login
    r = http.post(f"{base_url}/auth/login", json={"email": creds["email"], "password": creds["password"]})
    _expect_status(r, 200, "/auth/login")
    access = r.json().get("access_token")
    assert access, "missing access_token from /auth/login"
    http.headers["Authorization"] = f"Bearer {access}"
    return access, http

def ensure_family(http, base_url, name, description="seeded by tests"):
    r = http.get(f"{base_url}/family/all")
    _expect_status(r, 200, "/family/all")
    fid = next((row["id"] for row in r.json() if row.get("name")==name), None)
    if not fid:
        r = http.post(f"{base_url}/family/add", json={"name": name, "description": description})
        _expect_status(r, 201, "/family/add")
        fid = r.json().get("id")
    assert fid, "cannot ensure family"
    return fid

def find_plant_id(http, base_url, scientific_name):
    r = http.get(f"{base_url}/plants/all")
    if r.status_code == 200:
        for p in r.json():
            if p.get("scientific_name") == scientific_name:
                return p.get("id")
    return None
