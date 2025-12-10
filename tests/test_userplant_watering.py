# tests/test_userplant_watering.py
from conftest import ensure_family, find_plant_id, get_test_image_base64


def test_userplant_and_watering_flow(user_token_and_session, base_url):
    access, http = user_token_and_session

    # famiglia corretta
    fam_id = ensure_family(http, base_url, "Polypodiaceae")
    image_b64 = get_test_image_base64()

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
        "size": "small",
        "family_id": fam_id,
        "image": image_b64,
    }

    # 1) CREATE /plant/add con image + family_id
    r = http.post(f"{base_url}/plant/add", json=payload)
    if r.status_code == 201:
        plant_id = r.json().get("id")
    elif r.status_code in (409, 500):
        # pianta già presente o conflitto gestito lato server → la recuperiamo
        plant_id = find_plant_id(http, base_url, payload["scientific_name"])
    else:
        # errore reale
        assert False, f"plant/add failed: {r.status_code} {r.text}"

    assert plant_id, f"plant/add failed and cannot find existing plant: {r.text}"

    # 2) Provo a creare un watering_plan manuale
    r = http.post(
        f"{base_url}/watering_plan/add",
        json={
            "plant_id": plant_id,
            "next_due_at": "2030-01-01 08:00:00",
            "interval_days": 5,
        },
    )

    if r.status_code == 403:
        # non sono owner → divento proprietario
        r2 = http.post(f"{base_url}/user_plant/add", json={"plant_id": plant_id})
        assert r2.status_code in (200, 201), (
            f"user_plant/add failed: {r2.status_code} {r2.text}"
        )

        # riprovo watering_plan/add
        r = http.post(
            f"{base_url}/watering_plan/add",
            json={
                "plant_id": plant_id,
                "next_due_at": "2030-01-01 08:00:00",
                "interval_days": 5,
            },
        )

    # A QUESTO PUNTO:
    # - 201 → creato ora
    # - 409 → già esiste (creato da ReminderService su /plant/add)
    assert r.status_code in (201, 409), (
        f"watering_plan/add should create or report existing plan: "
        f"{r.status_code} {r.text}"
    )

    # 3) aggiungo un watering_log associato
    r = http.post(
        f"{base_url}/watering_log/add",
        json={
            "plant_id": plant_id,
            "done_at": "2030-01-01 08:05:00",
            "amount_ml": 200,
        },
    )
    assert r.status_code == 201, f"watering_log/add failed: {r.text}"
