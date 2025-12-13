import os
import uuid
import base64
import requests
from typing import Tuple, Dict, Any
import pytest

BASE_URL = "http://localhost:8000/api"


def _create_user_and_login(email: str, password: str = "secret123") -> Tuple[str, str]:
    """
    Crea un utente e fa il login, restituendo (access_token, user_id).
    """
    # create user (best effort)
    r = requests.post(
        f"{BASE_URL}/user/add",
        json={
            "email": email,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    # può restituire 201 (creato) o 409 (già esiste)
    assert r.status_code in (201, 409)

    # login
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"/auth/login -> {r.status_code} {r.text}"
    data = r.json()
    token = data["access_token"]
    user_id = data["user_id"]
    return token, user_id


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_first_plant_id(token: str) -> str:
    """
    Recupera una plant_id dal catalogo se esiste.
    Se il catalogo è vuoto, crea una pianta di test (autenticato) e
    la collega al garden dell’utente corrente.
    """
    # 1) Catalogo
    r = requests.get(f"{BASE_URL}/plants/all")
    assert r.status_code == 200, f"/plants/all -> {r.status_code} {r.text}"
    plants = r.json()
    if plants:
        # Se esiste già, assicurati di collegarla al garden dell'utente
        plant_id = plants[0]["id"]
        r = requests.post(
            f"{BASE_URL}/user_plant/add",
            json={"plant_id": plant_id},
            headers=_auth_headers(token),
        )
        # Potrebbe già essere collegata: accetta 200/201/409
        assert r.status_code in (200, 201, 409), f"/user_plant/add -> {r.status_code} {r.text}"
        return plant_id

    # 2) Catalogo vuoto → crea una pianta di servizio autenticata
    tests_dir = os.path.dirname(__file__)
    img_path = os.path.join(tests_dir, "test_plant.jpeg")
    with open(img_path, "rb") as f:
        img_bytes = f.read()
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")

    r = requests.post(
        f"{BASE_URL}/plant/add",
        json={"image": image_b64},
        headers=_auth_headers(token),
    )
    assert r.status_code == 201, f"/plant/add (autocreate) -> {r.status_code} {r.text}"
    plant_id = r.json()["id"]

    # 3) Collega la pianta al garden dell’utente
    r = requests.post(
        f"{BASE_URL}/user_plant/add",
        json={"plant_id": plant_id},
        headers=_auth_headers(token),
    )
    assert r.status_code in (200, 201, 409), f"/user_plant/add -> {r.status_code} {r.text}"
    return plant_id


def test_user_can_create_and_list_own_plants():
    # Arrange
    email = f"test+{uuid.uuid4().hex[:8]}@example.com"
    token, user_id = _create_user_and_login(email)

    # Act: ottieni/crea e collega una plant al garden
    plant_id = _get_first_plant_id(token)

    # Assert: l'utente vede la pianta nel proprio garden
    r = requests.get(f"{BASE_URL}/user_plant/all", headers=_auth_headers(token))
    assert r.status_code == 200, f"/user_plant/all -> {r.status_code} {r.text}"
    rows = r.json()
    assert isinstance(rows, list)
    plant_ids = {row.get("plant", {}).get("id") or row.get("plant_id") for row in rows}
    assert plant_id in plant_ids, "Created plant not found in the user's garden"


def test_auth_required_for_protected_endpoints():
    # /plants is protected (@require_jwt). Without token should be 401.
    r = requests.get(f"{BASE_URL}/plants")
    assert r.status_code == 401, f"/plants without token should be 401, got {r.status_code}"
