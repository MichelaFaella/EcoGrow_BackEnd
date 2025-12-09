import os, uuid, pytest, requests, base64
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def get_test_image_base64():
    """Loads the test plant image and returns it as base64 string."""
    image_path = TESTS_DIR / "test_plant.jpeg"
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@pytest.fixture(scope="session")
def base_url():
    """Returns the base API URL from environment or default."""
    return os.environ.get("BASE", "http://localhost:8000/api").rstrip("/")


@pytest.fixture(scope="session")
def creds():
    """Returns credentials for the primary test user."""
    email = os.environ.get("EMAIL") or f"tester_{uuid.uuid4().hex[:10]}@example.com"
    password = os.environ.get("PASS", "secret123")
    return {"email": email, "password": password}


@pytest.fixture(scope="session")
def http():
    """Returns a shared HTTP session for the primary test user."""
    return requests.Session()


def _expect_status(resp, code, msg=""):
    """Helper to assert expected HTTP status code."""
    assert resp.status_code == code, f"{msg} expected {code}, got {resp.status_code}, body={resp.text}"


@pytest.fixture(scope="session")
def user_token_and_session(http, base_url, creds):
    """
    Creates and authenticates the primary test user.
    Returns (access_token, http_session) with Authorization header set.
    """
    http.post(f"{base_url}/user/add", json={
        "email": creds["email"], "password": creds["password"],
        "first_name": "Test", "last_name": "User"
    })

    r = http.post(f"{base_url}/auth/login", json={
        "email": creds["email"], "password": creds["password"]
    })
    _expect_status(r, 200, "/auth/login")
    access = r.json().get("access_token")
    assert access, "missing access_token from /auth/login"
    http.headers["Authorization"] = f"Bearer {access}"
    return access, http


@pytest.fixture(scope="function")
def additional_user(base_url):
    """
    Creates an additional user for multi-user tests.
    A new user is created for each test and automatically deleted after.
    
    Returns a dict with: access_token, user_id, short_id, http, email
    """
    email = f"extra_{uuid.uuid4().hex[:8]}@test.local"
    password = "Secret123!"

    session = requests.Session()

    r = session.post(f"{base_url}/user/add", json={
        "email": email, "password": password,
        "first_name": "Extra", "last_name": "User"
    })
    assert r.status_code in (201, 409), f"/user/add failed: {r.status_code} {r.text}"

    r = session.post(f"{base_url}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"/auth/login failed: {r.status_code} {r.text}"
    data = r.json()

    session.headers["Authorization"] = f"Bearer {data['access_token']}"

    user_info = {
        "access_token": data["access_token"],
        "user_id": data["user_id"],
        "short_id": data["user_id"].split("-")[0],
        "http": session,
        "email": email
    }

    yield user_info

    session.delete(f"{base_url}/user/delete-me")


def ensure_family(http, base_url, name, description="seeded by tests"):
    """Ensures a plant family exists, creating it if necessary. Returns family ID."""
    r = http.get(f"{base_url}/family/all")
    _expect_status(r, 200, "/family/all")
    fid = next((row["id"] for row in r.json() if row.get("name") == name), None)
    if not fid:
        r = http.post(f"{base_url}/family/add", json={"name": name, "description": description})
        _expect_status(r, 201, "/family/add")
        fid = r.json().get("id")
    assert fid, "cannot ensure family"
    return fid


def find_plant_id(http, base_url, scientific_name):
    """Finds a plant ID by scientific name. Returns None if not found."""
    r = http.get(f"{base_url}/plants/all")
    if r.status_code == 200:
        for p in r.json():
            if p.get("scientific_name") == scientific_name:
                return p.get("id")
    return None
