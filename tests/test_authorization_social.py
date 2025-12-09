
import uuid
import requests
from typing import Tuple, Dict

BASE_URL = "http://localhost:8000/api"


def _create_user_and_login(email: str, password: str = "secret123") -> Tuple[str, str]:
    """
    Crea un utente e fa il login, restituendo (access_token, user_id).
    """
    r = requests.post(
        f"{BASE_URL}/user/add",
        json={
            "email": email,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert r.status_code in (201, 409)

    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"/auth/login -> {r.status_code} {r.text}"
    data = r.json()
    return data["access_token"], data["user_id"]


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_all_returns_only_current_user():
    """
    Verifica che /user/all ritorni solo l'utente corrente
    dopo la modifica di sicurezza.
    """
    email1 = f"userall1_{uuid.uuid4().hex}@example.com"
    email2 = f"userall2_{uuid.uuid4().hex}@example.com"

    token1, user1_id = _create_user_and_login(email1)
    token2, user2_id = _create_user_and_login(email2)

    r1 = requests.get(f"{BASE_URL}/user/all", headers=_auth_headers(token1))
    assert r1.status_code == 200
    rows1 = r1.json()
    assert len(rows1) == 1
    assert rows1[0]["id"] == user1_id

    r2 = requests.get(f"{BASE_URL}/user/all", headers=_auth_headers(token2))
    assert r2.status_code == 200
    rows2 = r2.json()
    assert len(rows2) == 1
    assert rows2[0]["id"] == user2_id


def test_friendship_only_members_can_update_and_delete():
    """
    Verifica che solo gli utenti coinvolti in una friendship
    possano aggiornarla o cancellarla.
    """
    email1 = f"fr1_{uuid.uuid4().hex}@example.com"
    email2 = f"fr2_{uuid.uuid4().hex}@example.com"
    email3 = f"fr3_{uuid.uuid4().hex}@example.com"

    token1, user1_id = _create_user_and_login(email1)
    token2, user2_id = _create_user_and_login(email2)
    token3, user3_id = _create_user_and_login(email3)

    # crea friendship tra user1 (A) e user2 (B) come user1
    r = requests.post(
        f"{BASE_URL}/friendship/add",
        headers=_auth_headers(token1),
        json={
            "user_id_b": user2_id,
            "status": "accepted",
        },
    )
    assert r.status_code == 201, f"/friendship/add -> {r.status_code} {r.text}"
    fr_id = r.json()["id"]

    # update come membro (user1) -> OK
    r = requests.patch(
        f"{BASE_URL}/friendship/update/{fr_id}",
        headers=_auth_headers(token1),
        json={"status": "blocked"},
    )
    assert r.status_code == 200

    # update come non-membro (user3) -> 403
    r = requests.patch(
        f"{BASE_URL}/friendship/update/{fr_id}",
        headers=_auth_headers(token3),
        json={"status": "accepted"},
    )
    assert r.status_code == 403

    # delete come non-membro (user3) -> 403
    r = requests.delete(
        f"{BASE_URL}/friendship/delete/{fr_id}",
        headers=_auth_headers(token3),
    )
    assert r.status_code == 403

    # delete come membro (user2) -> 204
    r = requests.delete(
        f"{BASE_URL}/friendship/delete/{fr_id}",
        headers=_auth_headers(token2),
    )
    assert r.status_code == 204
