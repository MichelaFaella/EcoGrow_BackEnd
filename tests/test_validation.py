# tests/test_validation.py
import uuid
from conftest import ensure_family, find_plant_id

def test_validation_branches(user_token_and_session, base_url):
    access, http = user_token_and_session

    # bad size on create
    sci = f"ValidX {uuid.uuid4().hex[:6]}"
    bad = {
        "scientific_name": sci,
        "common_name": "BadSize",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 3,
        "difficulty": 2,
        "min_temp_c": 10,
        "max_temp_c": 20,
        "category": "test",
        "climate": "temperate",
        "size": "ENORME"
    }
    r = http.post(f"{base_url}/plant/add", json=bad)
    assert r.status_code in (400, 500)

    # good: stessa specie ma size valida e con family_id
    fam_id = ensure_family(http, base_url, "Testaceae")
    good = bad.copy()
    good["size"] = "small"
    good["family_id"] = fam_id

    r = http.post(f"{base_url}/plant/add", json=good)
    pid = r.json().get("id") if r.status_code == 201 else None
    if not pid:
        pid = find_plant_id(http, base_url, sci)
    assert pid

    # plan invalid datetime
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "not-a-date", "interval_days": 5
    })
    assert r.status_code in (400, 403, 422)

    # plan negative interval
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "2030-01-01 08:00:00", "interval_days": -1
    })
    assert r.status_code in (400, 403, 422)

    # log invalid datetime
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": pid, "done_at": "not-a-date", "amount_ml": 100
    })
    assert r.status_code in (400, 403, 422)

    # log negative amount
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": pid, "done_at": "2030-01-01 09:00:00", "amount_ml": -50
    })
    assert r.status_code in (400, 403, 422)
