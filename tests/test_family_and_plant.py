import pytest
from conftest import ensure_family, find_plant_id, get_test_image_base64

SPECIES = "Aeschynanthus lobianus"
FAMILY  = "Gesneriaceae"


def test_family_required_for_plant(user_token_and_session, base_url):
    access, http = user_token_and_session

    # mi assicuro che la famiglia esista e recupero l'id
    fam_id = ensure_family(http, base_url, FAMILY)

    # uso sempre l'immagine di test: tests/test_plant.jpeg
    image_b64 = get_test_image_base64()

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
        "size": "medium",
        "family_id": fam_id,
        "image": image_b64,
    }

    # primo tentativo di creazione
    r = http.post(f"{base_url}/plant/add", json=payload)
    if r.status_code == 201:
        plant_id = r.json().get("id")
    elif r.status_code == 409:
        # pianta già esistente: la recupero
        plant_id = find_plant_id(http, base_url, SPECIES)
    else:
        # qualunque altro codice è un errore reale
        assert False, f"plant/add failed: {r.status_code} {r.text}"

    assert plant_id, "unable to create or find plant"

    # verifichiamo che l'endpoint di filtro per size funzioni
    r = http.get(f"{base_url}/plants/by-size/medium")
    assert r.status_code == 200
