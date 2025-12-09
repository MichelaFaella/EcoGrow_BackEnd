
import uuid
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
    Recupera una plant_id dal catalogo.
    """
    r = requests.get(f"{BASE_URL}/plants/all")
    assert r.status_code == 200, f"/plants/all -> {r.status_code} {r.text}"
    plants = r.json()
    assert plants, "Nessuna pianta nel catalogo: popola prima il DB"
    return plants[0]["id"]


def _user_add_plant_to_garden(token: str, plant_id: str) -> None:
    r = requests.post(
        f"{BASE_URL}/user_plant/add",
        headers=_auth_headers(token),
        json={"plant_id": plant_id},
    )
    # può restituire 201 (creato) o 200 (già presente)
    assert r.status_code in (200, 201), f"/user_plant/add -> {r.status_code} {r.text}"
    assert r.json().get("ok") is True


def test_watering_plan_and_log_and_reminder_ownership():
    """
    Verifica che:
    - watering_plan/all sia filtrato per utente
    - watering_plan/update/delete consentiti solo al proprietario
    - watering_log/all sia filtrato per utente
    - watering_log/update/delete consentiti solo al proprietario
    - reminder/all sia filtrato per utente
    - reminder/update/delete consentiti solo al proprietario
    """
    # crea 2 utenti
    email1 = f"user1_{uuid.uuid4().hex}@example.com"
    email2 = f"user2_{uuid.uuid4().hex}@example.com"

    token1, user1_id = _create_user_and_login(email1)
    token2, user2_id = _create_user_and_login(email2)

    plant_id = _get_first_plant_id()
    _user_add_plant_to_garden(token1, plant_id)

    # --- WateringPlan: creation by USER1 ---
    wp_next_due = "2025-01-01T10:00:00"
    r = requests.post(
        f"{BASE_URL}/watering_plan/add",
        headers=_auth_headers(token1),
        json={
            "plant_id": plant_id,
            "next_due_at": wp_next_due,
            "interval_days": 3,
        },
    )
    assert r.status_code == 201, f"/watering_plan/add -> {r.status_code} {r.text}"
    wp_id = r.json()["id"]

    # USER1 vede il piano, USER2 no
    r1 = requests.get(
        f"{BASE_URL}/watering_plan/all",
        headers=_auth_headers(token1),
    )
    assert r1.status_code == 200
    rows1 = r1.json()
    assert any(row["id"] == wp_id for row in rows1)

    r2 = requests.get(
        f"{BASE_URL}/watering_plan/all",
        headers=_auth_headers(token2),
    )
    assert r2.status_code == 200
    rows2 = r2.json()
    assert all(row["user_id"] == user2_id for row in rows2)
    assert not any(row["id"] == wp_id for row in rows2)

    # UPDATE: USER1 ok, USER2 forbidden
    r = requests.patch(
        f"{BASE_URL}/watering_plan/update/{wp_id}",
        headers=_auth_headers(token1),
        json={"interval_days": 4},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True

    r = requests.patch(
        f"{BASE_URL}/watering_plan/update/{wp_id}",
        headers=_auth_headers(token2),
        json={"interval_days": 5},
    )
    assert r.status_code == 403

    # DELETE: USER2 forbidden, USER1 ok
    r = requests.delete(
        f"{BASE_URL}/watering_plan/delete/{wp_id}",
        headers=_auth_headers(token2),
    )
    assert r.status_code == 403

    r = requests.delete(
        f"{BASE_URL}/watering_plan/delete/{wp_id}",
        headers=_auth_headers(token1),
    )
    assert r.status_code == 204

    # --- WateringLog: creation by USER1 ---
    wl_done_at = "2025-01-02T09:30:00"
    r = requests.post(
        f"{BASE_URL}/watering_log/add",
        headers=_auth_headers(token1),
        json={
            "plant_id": plant_id,
            "done_at": wl_done_at,
            "amount_ml": 200,
        },
    )
    assert r.status_code == 201, f"/watering_log/add -> {r.status_code} {r.text}"
    wl_id = r.json()["id"]

    # USER1 vede il log, USER2 no
    r1 = requests.get(
        f"{BASE_URL}/watering_log/all",
        headers=_auth_headers(token1),
    )
    assert r1.status_code == 200
    logs1 = r1.json()
    assert any(log["id"] == wl_id for log in logs1)

    r2 = requests.get(
        f"{BASE_URL}/watering_log/all",
        headers=_auth_headers(token2),
    )
    assert r2.status_code == 200
    logs2 = r2.json()
    assert all(log["user_id"] == user2_id for log in logs2)
    assert not any(log["id"] == wl_id for log in logs2)

    # UPDATE: USER1 ok, USER2 forbidden
    r = requests.patch(
        f"{BASE_URL}/watering_log/update/{wl_id}",
        headers=_auth_headers(token1),
        json={"amount_ml": 250},
    )
    assert r.status_code == 200

    r = requests.patch(
        f"{BASE_URL}/watering_log/update/{wl_id}",
        headers=_auth_headers(token2),
        json={"amount_ml": 300},
    )
    assert r.status_code == 403

    # DELETE: USER2 forbidden, USER1 ok
    r = requests.delete(
        f"{BASE_URL}/watering_log/delete/{wl_id}",
        headers=_auth_headers(token2),
    )
    assert r.status_code == 403

    r = requests.delete(
        f"{BASE_URL}/watering_log/delete/{wl_id}",
        headers=_auth_headers(token1),
    )
    assert r.status_code == 204

    # --- Reminder: creation by USER1 ---
    rem_sched = "2025-01-03T08:00:00"
    r = requests.post(
        f"{BASE_URL}/reminder/add",
        headers=_auth_headers(token1),
        json={
            "title": "Reminder test User1",
            "scheduled_at": rem_sched,
        },
    )
    assert r.status_code == 201, f"/reminder/add -> {r.status_code} {r.text}"
    rem_id = r.json()["id"]

    # USER1 vede il reminder, USER2 no
    r1 = requests.get(
        f"{BASE_URL}/reminder/all",
        headers=_auth_headers(token1),
    )
    assert r1.status_code == 200
    rems1 = r1.json()
    assert any(rem["id"] == rem_id for rem in rems1)

    r2 = requests.get(
        f"{BASE_URL}/reminder/all",
        headers=_auth_headers(token2),
    )
    assert r2.status_code == 200
    rems2 = r2.json()
    assert not any(rem["id"] == rem_id for rem in rems2)

    # UPDATE: USER1 ok, USER2 forbidden
    r = requests.patch(
        f"{BASE_URL}/reminder/update/{rem_id}",
        headers=_auth_headers(token1),
        json={"title": "Reminder aggiornato"},
    )
    assert r.status_code == 200

    r = requests.patch(
        f"{BASE_URL}/reminder/update/{rem_id}",
        headers=_auth_headers(token2),
        json={"title": "Reminder hackerato"},
    )
    assert r.status_code == 403

    # DELETE: USER2 forbidden, USER1 ok
    r = requests.delete(
        f"{BASE_URL}/reminder/delete/{rem_id}",
        headers=_auth_headers(token2),
    )
    assert r.status_code == 403

    r = requests.delete(
        f"{BASE_URL}/reminder/delete/{rem_id}",
        headers=_auth_headers(token1),
    )
    assert r.status_code == 204


def test_userplant_delete_only_affects_current_user():
    """
    Verifica che DELETE /user_plant/delete cancelli solo le piante
    nel giardino dell'utente loggato (usa sempre g.user_id).
    """
    email1 = f"up1_{uuid.uuid4().hex}@example.com"
    email2 = f"up2_{uuid.uuid4().hex}@example.com"

    token1, user1_id = _create_user_and_login(email1)
    token2, user2_id = _create_user_and_login(email2)

    plant_id = _get_first_plant_id()

    # USER1 aggiunge la pianta al proprio giardino
    _user_add_plant_to_garden(token1, plant_id)

    # USER2 prova a cancellare quella pianta dal proprio giardino
    r = requests.delete(
        f"{BASE_URL}/user_plant/delete",
        headers=_auth_headers(token2),
        params={"plant_id": plant_id},
    )
    # anche se torna 204, non deve aver toccato il giardino di USER1
    assert r.status_code == 204

    # USER1 continua ad avere la pianta
    r1 = requests.get(
        f"{BASE_URL}/user_plant/all",
        headers=_auth_headers(token1),
    )
    assert r1.status_code == 200
    ups1 = r1.json()
    assert any(up["plant_id"] == plant_id for up in ups1)

    # USER2 non ha la pianta
    r2 = requests.get(
        f"{BASE_URL}/user_plant/all",
        headers=_auth_headers(token2),
    )
    assert r2.status_code == 200
    ups2 = r2.json()
    assert all(up["plant_id"] != plant_id for up in ups2)


def test_shared_plant_owner_only_update_and_delete():
    """
    Verifica che:
    - solo l'owner possa fare update/delete su SharedPlant
    - il recipient non possa modificare o chiudere la condivisione
    """
    email1 = f"sp1_{uuid.uuid4().hex}@example.com"
    email2 = f"sp2_{uuid.uuid4().hex}@example.com"

    token1, user1_id = _create_user_and_login(email1)
    token2, user2_id = _create_user_and_login(email2)

    plant_id = _get_first_plant_id()
    _user_add_plant_to_garden(token1, plant_id)

    # ricava lo short_id del recipient (prima parte dell'UUID)
    short_id_2 = user2_id.split("-")[0]

    # crea shared_plant come OWNER (user1)
    r = requests.post(
        f"{BASE_URL}/shared_plant/add",
        headers=_auth_headers(token1),
        json={
            "plant_id": plant_id,
            "short_id": short_id_2,
            "can_edit": True,
        },
    )
    assert r.status_code == 201 or r.status_code == 200, (
        f"/shared_plant/add -> {r.status_code} {r.text}"
    )
    body = r.json()
    sp_id = body.get("shared_id") or body.get("id")
    assert sp_id, f"SharedPlant id non trovato in risposta: {body}"

    # update come OWNER -> OK
    r = requests.patch(
        f"{BASE_URL}/shared_plant/update/{sp_id}",
        headers=_auth_headers(token1),
        json={"can_edit": False},
    )
    assert r.status_code == 200

    # update come RECIPIENT -> 403
    r = requests.patch(
        f"{BASE_URL}/shared_plant/update/{sp_id}",
        headers=_auth_headers(token2),
        json={"can_edit": True},
    )
    assert r.status_code == 403

    # delete come RECIPIENT -> 404 o 403 (in base alla tua implementazione)
    r = requests.delete(
        f"{BASE_URL}/shared_plant/delete/{sp_id}",
        headers=_auth_headers(token2),
    )
    assert r.status_code in (403, 404)

    # delete come OWNER -> 204
    r = requests.delete(
        f"{BASE_URL}/shared_plant/delete/{sp_id}",
        headers=_auth_headers(token1),
    )
    assert r.status_code == 204
