from conftest import ensure_family, find_plant_id

def test_userplant_and_watering_flow(user_token_and_session, base_url):
    access, http = user_token_and_session

    payload = {
        "scientific_name": "Adiantum raddianum",
        "common_name": "Maidenhair fern",
        "use": "ornamental",
        "water_level": 3,
        "light_level": 3,
        "difficulty": 3,
        "min_temp_c": 15,
        "max_temp_c": 28,
        "category": "fern",
        "climate": "tropical",
        "size": "small"
    }
    ensure_family(http, base_url, "Polypodiaceae")

    r = http.post(f"{base_url}/plant/add", json=payload)
    if r.status_code == 201:
        plant_id = r.json().get("id")
    else:
        # pianta già presente (409/500)? prova a recuperare
        plant_id = find_plant_id(http, base_url, payload["scientific_name"])
    assert plant_id, f"plant/add failed and cannot find existing plant: {r.text}"

    # Watering plan dovrebbe inizialmente fallire senza ownership
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": plant_id,
        "next_due_at": "2030-01-01 08:00:00",
        "interval_days": 5
    })
    if r.status_code == 403:
        # link ownership
        r2 = http.post(f"{base_url}/user_plant/add", json={"plant_id": plant_id})
        assert r2.status_code in (200, 201)

        r = http.post(f"{base_url}/watering_plan/add", json={
            "plant_id": plant_id,
            "next_due_at": "2030-01-01 08:00:00",
            "interval_days": 5
        })
    assert r.status_code == 201, f"watering_plan/add should succeed: {r.status_code} {r.text}"

    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": plant_id,
        "done_at": "2030-01-01 08:05:00",
        "amount_ml": 200
    })
    assert r.status_code == 201, f"watering_log/add failed: {r.text}"
