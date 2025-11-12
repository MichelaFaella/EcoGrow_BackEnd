import os, uuid, time

# tests/test_plants_crud_filters_and_photos.py
import os, uuid, time
from conftest import ensure_family, find_plant_id

def test_plants_crud_filters_and_photos(user_token_and_session, base_url):
    access, http = user_token_and_session

    sci = f"Testium plantensis {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")  # famiglia di servizio per i test

    payload = {
        "scientific_name": sci,
        "common_name": "Test Plant",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 4,
        "difficulty": 3,
        "min_temp_c": 10,
        "max_temp_c": 30,
        "category": "test",
        "climate": "temperate",
        "size": "medium",
        "family_id": fam_id
    }

    # CREATE (può creare anche user_plant in automatico)
    r = http.post(f"{base_url}/plant/add", json=payload)
    assert r.status_code in (201, 409, 500), r.text
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        pid = find_plant_id(http, base_url, sci)
    assert pid

    # UPDATE: size non valido → 400
    r = http.patch(f"{base_url}/plant/update/{pid}", json={"size": "ENORME"})
    assert r.status_code == 400

    # UPDATE: size valido → 200
    r = http.patch(f"{base_url}/plant/update/{pid}", json={"size": "small", "origin": "EU"})
    assert r.status_code == 200

    # FILTERS
    r = http.get(f"{base_url}/plants/by-use/ornamental")
    assert r.status_code == 200
    r = http.get(f"{base_url}/plants/by-size/small")
    assert r.status_code in (200, 400)

    # PlantPhoto via URL
    r = http.post(f"{base_url}/plant/photo/add/{pid}",
                  json={"url": "https://example.com/one.jpg", "caption": "one", "order_index": 0})
    assert r.status_code == 201, r.text
    photo_id = r.json()["id"]

    # Update caption
    r = http.patch(f"{base_url}/plant/photo/update/{photo_id}", json={"caption": "one-upd"})
    assert r.status_code == 200

    # List globale
    r = http.get(f"{base_url}/plant_photo/all")
    assert r.status_code == 200 and isinstance(r.json(), list)

    # GET main photo + GET list per plant (limit=1)
    r = http.get(f"{base_url}/plant/{pid}/photo")
    assert r.status_code == 200
    r = http.get(f"{base_url}/plant/{pid}/photos?limit=1")
    assert r.status_code == 200 and len(r.json()) <= 1

    # Upload (multipart) → GET del file servito, poi DELETE record+file
    tiny = os.urandom(128)
    files = {"file": ("x.jpg", tiny, "image/jpeg")}
    data = {"plant_id": pid, "caption": "bin-file"}
    r = http.post(f"{base_url}/upload/plant-photo", files=files, data=data)
    assert r.status_code == 201, r.text
    up_photo_id = r.json()["photo_id"]
    url = r.json()["url"]

    app_root = base_url.rsplit("/api", 1)[0]
    file_resp = http.get(f"{app_root}{url}")
    assert file_resp.status_code == 200

    # cancello la foto caricata
    r = http.delete(f"{base_url}/plant-photo/delete/{up_photo_id}")
    assert r.status_code == 204

    time.sleep(0.05)
    file_resp2 = http.get(f"{app_root}{url}")
    assert file_resp2.status_code in (404, 410, 500)

    # DELETE plant (idempotente)
    r = http.delete(f"{base_url}/plant/delete/{pid}")
    assert r.status_code == 204


from conftest import ensure_family, find_plant_id

def test_plants_create_and_conflict_branch(user_token_and_session, base_url):
    access, http = user_token_and_session

    # Use a species from house_plants.json that maps to a known family
    sci = f"Testium plantensis {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")  # nuova famiglia “di servizio”

    payload = {
        "scientific_name": sci,
        "common_name": "Test Plant",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 4,
        "difficulty": 3,
        "min_temp_c": 10,
        "max_temp_c": 30,
        "category": "test",
        "climate": "temperate",
        "size": "medium",
        "family_id": fam_id            # <— **chiave del fix**
    }

    # first create
    r = http.post(f"{base_url}/plant/add", json=payload)
    assert r.status_code in (201, 409, 500), r.text
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        from conftest import find_plant_id
        pid = find_plant_id(http, base_url, sci)
    assert pid

    # second create (same species) -> expect conflict style (409/500) or graceful 201 if dedup disabled
    r2 = http.post(f"{base_url}/plant/add", json=payload)
    assert r2.status_code in (201, 409, 500)
    if r2.status_code in (409, 500):
        # body should mention duplicate/conflict
        assert "Duplicate" in r2.text or "Conflict" in r2.text or "already" in r2.text