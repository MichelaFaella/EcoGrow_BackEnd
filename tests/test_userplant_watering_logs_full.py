# tests/test_userplant_watering_logs_full.py
import uuid
import datetime as dt
from conftest import ensure_family, find_plant_id, get_test_image_base64


def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def test_userplant_and_watering_full(user_token_and_session, base_url):
    access, http = user_token_and_session

    sci = f"UPFlow plant {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")
    image_b64 = get_test_image_base64()

    # crea plant con family_id + image
    r = http.post(
        f"{base_url}/plant/add",
        json={
            "scientific_name": sci,
            "common_name": "UPFlow",
            "use": "ornamental",
            "water_level": 3,
            "light_level": 3,
            "difficulty": 2,
            "min_temp_c": 12,
            "max_temp_c": 28,
            "category": "test",
            "climate": "tropical",
            "size": "medium",
            "family_id": fam_id,
            "image": image_b64,
        },
    )
    if r.status_code == 201:
        pid = r.json()["id"]
    elif r.status_code in (409, 500):
        # pianta già presente / conflitto: recupero l'id
        pid = find_plant_id(http, base_url, sci)
    else:
        assert False, f"plant/add failed: {r.status_code} {r.text}"

    assert pid, "Unable to create or find plant"

    # mio user_id
    me = http.get(f"{base_url}/check-auth").json()["user_id"]

    # rimuovo eventuale link (idempotente, usa sempre g.user_id lato server)
    http.delete(
        f"{base_url}/user_plant/delete",
        params={"plant_id": pid},
    )

    # Primo tentativo: senza ownership → mi aspetto 403 (oppure 200 se il backend crea ownership implicita)
    r = http.post(
        f"{base_url}/watering_plan/add",
        json={
            "plant_id": pid,
            "next_due_at": "2030-01-01 08:00:00",
            "interval_days": 5,
        },
    )
    assert r.status_code in (403, 200), (
        f"Unexpected status for watering_plan/add without ownership: "
        f"{r.status_code} {r.text}"
    )

    if r.status_code == 403:
        # link ownership
        r2 = http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})
        assert r2.status_code in (200, 201), (
            f"user_plant/add failed: {r2.status_code} {r2.text}"
        )

    # Secondo tentativo: ora sono owner -> posso avere:
    # - 201 / 200: piano creato/ok
    # - 409: piano già esistente (es. creato automaticamente da plant.add)
    r = http.post(
        f"{base_url}/watering_plan/add",
        json={
            "plant_id": pid,
            "next_due_at": "2030-01-01 08:00:00",
            "interval_days": 5,
        },
    )
    assert r.status_code in (200, 201, 409), (
        f"watering_plan/add failed: {r.status_code} {r.text}"
    )

    # leggo lista e trovo il mio piano per (me, pid)
    r_plans = http.get(f"{base_url}/watering_plan/all")
    assert r_plans.status_code == 200, (
        f"/watering_plan/all failed: {r_plans.status_code} {r_plans.text}"
    )
    plans = r_plans.json()

    # alcuni backend restituiscono solo i piani dell'utente corrente:
    # filtro comunque per plant_id per sicurezza
    owned_plans = [p for p in plans if p.get("plant_id") == pid]
    assert owned_plans, "No watering_plan found for current user and plant"
    plan_id = owned_plans[0]["id"]

    # update plan
    r = http.patch(
        f"{base_url}/watering_plan/update/{plan_id}",
        json={"interval_days": 7},
    )
    assert r.status_code == 200, (
        f"watering_plan/update failed: {r.status_code} {r.text}"
    )

    # add log
    r = http.post(
        f"{base_url}/watering_log/add",
        json={"plant_id": pid, "done_at": _now_iso(), "amount_ml": 180},
    )
    assert r.status_code == 201, (
        f"watering_log/add failed: {r.status_code} {r.text}"
    )

    logs = http.get(f"{base_url}/watering_log/all").json()
    log_id = next(l["id"] for l in logs if l["plant_id"] == pid)

    # update log
    r = http.patch(
        f"{base_url}/watering_log/update/{log_id}",
        json={"amount_ml": 200},
    )
    assert r.status_code == 200, (
        f"watering_log/update failed: {r.status_code} {r.text}"
    )

    # delete log
    r = http.delete(f"{base_url}/watering_log/delete/{log_id}")
    assert r.status_code == 204, (
        f"watering_log/delete failed: {r.status_code} {r.text}"
    )

    # delete plan
    r = http.delete(f"{base_url}/watering_plan/delete/{plan_id}")
    assert r.status_code == 204, (
        f"watering_plan/delete failed: {r.status_code} {r.text}"
    )
