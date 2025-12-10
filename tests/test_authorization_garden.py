import os
import uuid
import base64
import requests
from typing import Tuple, Dict, Any

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


def _get_first_plant_id() -> str:
    """
    Recupera una plant_id dal catalogo se esiste.
    Se il catalogo è vuoto, crea una pianta di test usando tests/test_plant.jpeg
    e restituisce il suo id.
    """
    # 1) Provo a leggere il catalogo
    r = requests.get(f"{BASE_URL}/plants/all")
    assert r.status_code == 200, f"/plants/all -> {r.status_code} {r.text}"
    plants = r.json()

    if plants:
        return plants[0]["id"]

    # 2) Nessuna pianta nel catalogo → ne creo una di servizio
    tests_dir = os.path.dirname(__file__)
    img_path = os.path.join(tests_dir, "test_plant.jpeg")
    with open(img_path, "rb") as f:
        img_bytes = f.read()
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")

    payload = {
        "image": image_b64,
    }

    r = requests.post(f"{BASE_URL}/plant/add", json=payload)
    assert r.status_code == 201, f"/plant/add (autocreate) -> {r.status_code} {r.text}"
    plant_id = r.json()["id"]
    return plant_id
