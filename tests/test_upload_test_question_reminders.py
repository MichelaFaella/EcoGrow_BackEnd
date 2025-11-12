# tests/test_upload_test_question_reminders.py
import os
from conftest import ensure_family, find_plant_id

def test_upload_and_misc(user_token_and_session, base_url):
    access, http = user_token_and_session

    # Make a small plant to attach photo to
    ensure_family(http, base_url, "Bromeliaceae")
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
        "size": "medium"
    }
    r = http.post(f"{base_url}/plant/add", json=payload)
    plant_id = r.json().get("id") if r.status_code == 201 else None
    if not plant_id:
        plant_id = find_plant_id(http, base_url, payload["scientific_name"])
    assert plant_id

    # Upload photo (multipart/form-data)
    tiny = os.urandom(96)
    files = {"file": ("tiny.jpg", tiny, "image/jpeg")}
    data = {"plant_id": plant_id, "caption": "test-photo"}
    r = http.post(f"{base_url}/upload/plant-photo", files=files, data=data)
    assert r.status_code == 201, f"upload/plant-photo failed: {r.text}"

    # Question
    r = http.post(f"{base_url}/question/add", json={"text": "Serve luce diretta?", "type": "note"})
    assert r.status_code == 201, f"question/add failed: {r.text}"

    # Reminder
    r = http.post(f"{base_url}/reminder/add", json={"title": "Controlla parassiti", "scheduled_at": "2030-01-02 09:00:00"})
    assert r.status_code == 201, f"reminder/add failed: {r.text}"

def test_upload_negative_cases(user_token_and_session, base_url):
    access, http = user_token_and_session

    # missing file
    r = http.post(f"{base_url}/upload/plant-photo", data={"plant_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code in (400, 422)

    # invalid plant_id format → alcuni backend rispondono 404
    files = {"file": ("x.jpg", os.urandom(64), "image/jpeg")}
    r = http.post(f"{base_url}/upload/plant-photo", files=files, data={"plant_id": "not-a-uuid"})
    assert r.status_code in (400, 404, 422)
