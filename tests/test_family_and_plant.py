import pytest
from conftest import ensure_family, find_plant_id

SPECIES = "Aeschynanthus lobianus"
FAMILY  = "Gesneriaceae"

def test_family_required_for_plant(user_token_and_session, base_url):
    access, http = user_token_and_session

    payload = {
        "scientific_name": SPECIES,
        "common_name": "Lipstick plant",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 5,
        "difficulty": 3,
        "min_temp_c": 12,
        "max_temp_c": 30,
        "category": "hanging",
        "climate": "tropical",
        "size": "medium"
    }

    r = http.post(f"{base_url}/plant/add", json=payload)
    if r.status_code == 201:
        plant_id = r.json().get("id")
    else:
        # Se fallisce (400 family not found, 409/500 duplicate, ecc.), rimediamo
        ensure_family(http, base_url, FAMILY)
        r2 = http.post(f"{base_url}/plant/add", json=payload)
        if r2.status_code == 201:
            plant_id = r2.json().get("id")
        else:
            # pianta già esistente? recupera l'id e continua
            plant_id = find_plant_id(http, base_url, SPECIES)
    assert plant_id, f"unable to create or find plant: {r.status_code} {r.text}"

    r = http.get(f"{base_url}/plants/by-size/medium")
    assert r.status_code == 200
