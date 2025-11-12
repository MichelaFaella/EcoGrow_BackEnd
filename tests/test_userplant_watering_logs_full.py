# tests/test_userplant_watering_logs_full.py
import uuid, datetime as dt
from conftest import ensure_family, find_plant_id

def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

def test_userplant_and_watering_full(user_token_and_session, base_url):
    access, http = user_token_and_session

    sci = f"UPFlow plant {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")

    r = http.post(f"{base_url}/plant/add", json={
        "scientific_name": sci, "common_name": "UPFlow",
        "use": "ornamental","water_level": 3,"light_level": 3,"difficulty": 2,
        "min_temp_c": 12,"max_temp_c": 28,"category": "test","climate": "tropical","size": "medium",
        "family_id": fam_id
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        pid = find_plant_id(http, base_url, sci)
    assert pid

    # mio user_id
    me = http.get(f"{base_url}/check-auth").json()["user_id"]

    # rimuovo eventuale link (idempotente)
    http.delete(f"{base_url}/user_plant/delete", params={"user_id": me, "plant_id": pid})

    # 403: non owner → non posso creare piano
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "2030-01-01 08:00:00", "interval_days": 5
    })
    assert r.status_code in (403, 200)
    if r.status_code == 403:
        http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})

    # add plan
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "2030-01-01 08:00:00", "interval_days": 5
    })
    assert r.status_code in (200, 201)

    # leggo lista e trovo il mio
    plans = http.get(f"{base_url}/watering_plan/all").json()
    plan_id = next(p["id"] for p in plans if p["plant_id"] == pid)

    # update plan
    r = http.patch(f"{base_url}/watering_plan/update/{plan_id}", json={"interval_days": 7})
    assert r.status_code == 200

    # add log
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": pid, "done_at": _now_iso(), "amount_ml": 180
    })
    assert r.status_code == 201
    logs = http.get(f"{base_url}/watering_log/all").json()
    log_id = next(l["id"] for l in logs if l["plant_id"] == pid)

    # update log
    r = http.patch(f"{base_url}/watering_log/update/{log_id}", json={"amount_ml": 200})
    assert r.status_code == 200

    # delete log
    r = http.delete(f"{base_url}/watering_log/delete/{log_id}")
    assert r.status_code == 204

    # delete plan
    r = http.delete(f"{base_url}/watering_plan/delete/{plan_id}")
    assert r.status_code == 204
