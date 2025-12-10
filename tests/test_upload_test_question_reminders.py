# tests/test_upload_test_question_reminders.py
import os
from conftest import ensure_family, find_plant_id, get_test_image_base64


def test_upload_and_misc(user_token_and_session, base_url):
    access, http = user_token_and_session

    # Make a small plant to attach photo to
    fam_id = ensure_family(http, base_url, "Bromeliaceae")
    image_b64 = get_test_image_base64()

    payload = {
        "scientific_name": "Aechmea fasciata",  # nome corretto
        "common_name": "Aechmea",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 4,
        "difficulty": 3,
        "min_temp_c": 14,
        "max_temp_c": 32,
        "category": "bromeliad",
        "climate": "tropical",
        "size": "medium",
        "family_id": fam_id,
        "image": image_b64,
    }

    r = http.post(f"{base_url}/plant/add", json=payload)
    if r.status_code == 201:
        plant_id = r.json().get("id")
    elif r.status_code in (409, 500):
        # pianta già esistente o conflitto gestito server-side → la recuperiamo
        plant_id = find_plant_id(http, base_url, payload["scientific_name"])
    else:
        assert False, f"plant/add failed: {r.status_code} {r.text}"

    assert plant_id, "unable to create or find plant"

    # Upload photo (multipart/form-data)
    tiny = os.urandom(96)
    files = {"file": ("tiny.jpg", tiny, "image/jpeg")}
    data = {"plant_id": plant_id, "caption": "test-photo"}
    r = http.post(f"{base_url}/upload/plant-photo", files=files, data=data)
    assert r.status_code == 201, f"upload/plant-photo failed: {r.text}"

    # Question (ora richiede anche options non vuoto)
    question_payload = {
        "text": "Serve luce diretta?",
        "type": "note",
        "active": True,
        "options": ["Sì", "No"],
    }
    r = http.post(f"{base_url}/question/add", json=question_payload)
    assert r.status_code == 201, f"question/add failed: {r.text}"

    # Reminder
    r = http.post(
        f"{base_url}/reminder/add",
        json={
            "title": "Controlla parassiti",
            "scheduled_at": "2030-01-02 09:00:00",
        },
    )
    assert r.status_code == 201, f"reminder/add failed: {r.text}"


def test_upload_negative_cases(user_token_and_session, base_url):
    access, http = user_token_and_session

    # missing file
    r = http.post(
        f"{base_url}/upload/plant-photo",
        data={"plant_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code in (400, 422)

    # invalid plant_id format → alcuni backend rispondono 404
    files = {"file": ("x.jpg", os.urandom(64), "image/jpeg")}
    r = http.post(
        f"{base_url}/upload/plant-photo",
        files=files,
        data={"plant_id": "not-a-uuid"},
    )
    assert r.status_code in (400, 404, 422)
