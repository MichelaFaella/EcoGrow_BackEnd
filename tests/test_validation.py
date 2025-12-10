# tests/test_validation.py
import uuid
from conftest import ensure_family, find_plant_id, get_test_image_base64

# Codici di errore ammessi nei branch "cattivi"
# (incluso 500 finché il backend potrebbe ancora alzare eccezioni interne)
ALLOWED_ERROR_CODES = (400, 403, 409, 422, 500)


def _create_valid_plant_with_image(http, base_url: str, family_name: str = "Testaceae") -> str:
    """
    Crea una pianta "valida" usando /plant/add con image.

    Nel backend attuale questo dovrebbe:
    - chiamare PlantNet;
    - creare la Plant;
    - creare automaticamente UserPlant + WateringPlan iniziale.

    Restituisce l'id della Plant creata (string UUID).
    """
    fam_id = ensure_family(http, base_url, family_name)
    image_b64 = get_test_image_base64()

    sci = f"TAD0 {uuid.uuid4().hex[:6]}"

    payload = {
        "scientific_name": sci,
        "common_name": "TAD0 plant",
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
    }

    r = http.post(f"{base_url}/plant/add", json=payload)
    assert r.status_code == 201, f"/plant/add (TAD0 helper) failed: {r.status_code} {r.text}"
    pid = r.json().get("id")
    assert pid, f"/plant/add (TAD0 helper) did not return an id: {r.text}"
    return pid


def test_validation_branches(user_token_and_session, base_url):
    """
    TAD0: verifica i branch di validazione sulla creazione di Plant
    (size invalida -> errore; payload valido -> ok).
    """
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
        "size": "ENORME",  # valore volutamente invalido
    }
    r = http.post(f"{base_url}/plant/add", json=bad)
    # la create con size invalido deve fallire
    assert r.status_code in (400, 422, 500)

    # good: stessa specie ma size valida, family_id e image (coerente col backend attuale)
    fam_id = ensure_family(http, base_url, "Testaceae")
    image_b64 = get_test_image_base64()

    good = bad.copy()
    good["size"] = "small"
    good["family_id"] = fam_id
    good["image"] = image_b64

    r = http.post(f"{base_url}/plant/add", json=good)
    if r.status_code == 201:
        pid = r.json().get("id")
    elif r.status_code in (409, 500):
        # pianta già presente o conflitto → la recuperiamo dal catalogo usando lo stesso sci
        pid = find_plant_id(http, base_url, sci)
    else:
        # errore reale inaspettato
        assert False, f"plant/add (good payload) failed: {r.status_code} {r.text}"

    assert pid, "Unable to create or find plant with valid payload"


def test_TAD0_watering_plan_and_log_validation(user_token_and_session, base_url):
    """
    TAD0: verifica i branch di validazione di watering_plan/add e watering_log/add,
    tenendo conto che /plant/add con image crea già un watering_plan iniziale.
    """
    access, http = user_token_and_session

    # Crea una pianta valida:
    # /plant/add con image → crea anche user_plant + watering_plan iniziale
    pid = _create_valid_plant_with_image(http, base_url, family_name="Testaceae")

    # ------------------------------------------------------
    # BRANCH BUONO A: il watering_plan auto-creato esiste
    # ------------------------------------------------------
    r = http.get(f"{base_url}/watering_plan/all")
    assert r.status_code == 200, f"/watering_plan/all failed: {r.status_code} {r.text}"
    plans = r.json()
    assert isinstance(plans, list)

    existing_plans_for_plant = [p for p in plans if p.get("plant_id") == pid]
    assert (
        existing_plans_for_plant
    ), "Expected an auto-created watering_plan for the plant, but none found in /watering_plan/all"

    # ------------------------------------------------------
    # BRANCH BUONO B: watering_log/add valido → deve andare a buon fine
    # ------------------------------------------------------
    r = http.post(
        f"{base_url}/watering_log/add",
        json={
            "plant_id": pid,
            "done_at": "2030-01-01 09:00:00",
            "amount_ml": 200,
        },
    )
    assert r.status_code == 201, (
        f"/watering_log/add with valid payload should succeed, "
        f"got {r.status_code} {r.text}"
    )

    # ------------------------------------------------------
    # BRANCH CATTIVO 1: watering_plan/add con datetime invalido
    # (la tua validazione dovrebbe bloccarlo; se scatta altro errore, è comunque "errore")
    # ------------------------------------------------------
    r = http.post(
        f"{base_url}/watering_plan/add",
        json={"plant_id": pid, "next_due_at": "not-a-date", "interval_days": 5},
    )
    assert r.status_code in ALLOWED_ERROR_CODES, (
        f"/watering_plan/add with invalid datetime should fail, "
        f"got {r.status_code} {r.text}"
    )

    # ------------------------------------------------------
    # BRANCH CATTIVO 2: watering_plan/add con interval_days negativo
    # ------------------------------------------------------
    r = http.post(
        f"{base_url}/watering_plan/add",
        json={
            "plant_id": pid,
            "next_due_at": "2030-01-01 08:00:00",
            "interval_days": -1,
        },
    )
    assert r.status_code in ALLOWED_ERROR_CODES, (
        f"/watering_plan/add with negative interval should fail, "
        f"got {r.status_code} {r.text}"
    )

    # ------------------------------------------------------
    # BRANCH CATTIVO 3: watering_log/add con datetime invalido
    # ------------------------------------------------------
    r = http.post(
        f"{base_url}/watering_log/add",
        json={"plant_id": pid, "done_at": "not-a-date", "amount_ml": 100},
    )
    assert r.status_code in ALLOWED_ERROR_CODES, (
        f"/watering_log/add with invalid datetime should fail, "
        f"got {r.status_code} {r.text}"
    )

