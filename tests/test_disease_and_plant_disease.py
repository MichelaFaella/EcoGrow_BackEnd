import uuid
import io
import base64
from conftest import ensure_family, find_plant_id, get_test_image_base64


def test_disease_and_plant_disease(user_token_and_session, base_url):
    access, http = user_token_and_session

    # disease
    name = f"Rust_{uuid.uuid4().hex[:6]}"
    r = http.post(f"{base_url}/disease/add", json={"name": name, "description": "fungal"})
    assert r.status_code == 201, r.text
    dis_id = r.json()["id"]

    r = http.patch(f"{base_url}/disease/update/{dis_id}", json={"treatment": "sulfur"})
    assert r.status_code == 200

    # ensure plant (con family) e ownership
    sci = f"DZ host {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={
        "scientific_name": sci,
        "common_name": "DZHost",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 3,
        "difficulty": 2,
        "min_temp_c": 10,
        "max_temp_c": 25,
        "category": "test",
        "climate": "temperate",
        "size": "medium",
        "family_id": fam_id,
        "image": image_b64,
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        # Se non è un conflitto (409), fallisci subito
        if r.status_code != 409:
            assert r.status_code == 201, f"plant/add failed: {r.text}"
        pid = find_plant_id(http, base_url, sci)

    assert pid, f"Could not find or create plant with scientific_name={sci}"

    # possiedo la plant (richiesto da alcune route)
    http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})

    # link plant_disease
    r = http.post(
        f"{base_url}/plant_disease/add",
        json={"plant_id": pid, "disease_id": dis_id, "severity": 2, "notes": "leaf spots"},
    )
    assert r.status_code in (201, 200), r.text
    pd_id = r.json().get("id")
    assert pd_id

    # update link
    r = http.patch(
        f"{base_url}/plant_disease/update/{pd_id}",
        json={"severity": 3, "status": "treated"},
    )
    assert r.status_code == 200

    # cleanup link e disease
    r = http.delete(f"{base_url}/plant_disease/delete/{pd_id}")
    assert r.status_code == 204
    r = http.delete(f"{base_url}/disease/delete/{dis_id}")
    assert r.status_code == 204


def test_disease_and_plant_disease_extended(user_token_and_session, base_url):
    """
    Versione estesa: stessa logica del test base, ma con una disease diversa.
    Usa l'immagine tests/test_plant.jpeg via get_test_image_base64(), così
    l'inserimento della pianta è robusto come nel primo test.
    """
    access, http = user_token_and_session

    # create disease
    name = f"LeafRust_{uuid.uuid4().hex[:6]}"
    r = http.post(f"{base_url}/disease/add", json={"name": name, "description": "fungal"})
    assert r.status_code == 201, r.text
    dis_id = r.json()["id"]

    # ensure plant (con family) e ownership usando l'immagine di test
    sci = f"DZ extended host {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={
        "scientific_name": sci,
        "common_name": "DZHostExtended",
        "use": "ornamental",
        "water_level": 2,
        "light_level": 3,
        "difficulty": 2,
        "min_temp_c": 10,
        "max_temp_c": 25,
        "category": "test",
        "climate": "temperate",
        "size": "medium",
        "family_id": fam_id,
        "image": image_b64,
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        # Se non è un conflitto (409), fallisci subito
        if r.status_code != 409:
            assert r.status_code == 201, f"plant/add failed: {r.text}"
        pid = find_plant_id(http, base_url, sci)

    assert pid, f"Could not find or create extended plant with scientific_name={sci}"

    # possiedo la plant (alcune API relazionali richiedono ownership)
    http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})

    # link plant_disease
    r = http.post(
        f"{base_url}/plant_disease/add",
        json={"plant_id": pid, "disease_id": dis_id, "severity": 2, "notes": "leaf spots"},
    )
    assert r.status_code in (201, 200), r.text
    pd_id = r.json().get("id")
    assert pd_id

    # update
    r = http.patch(
        f"{base_url}/plant_disease/update/{pd_id}",
        json={"severity": 3, "status": "treated"},
    )
    assert r.status_code == 200

    # cleanup (solo la disease; la pianta la lasciano gli altri test o si può eliminare qui se vuoi)
    r = http.delete(f"{base_url}/disease/delete/{dis_id}")
    assert r.status_code == 204


def test_disease_detection_simple(user_token_and_session, base_url):
    """Simple test to verify disease detection endpoint works and returns expected structure."""
    access, http = user_token_and_session

    image_b64 = get_test_image_base64()

    # First create a plant to associate the disease detection with
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    assert r.status_code == 201, f"plant/add failed: {r.text}"
    plant_id = r.json()["id"]

    # Decode base64 to bytes for multipart upload
    image_bytes = base64.b64decode(image_b64)

    files = {
        "image": ("test_plant.jpg", io.BytesIO(image_bytes), "image/jpeg")
    }
    data = {
        "plant_id": plant_id
    }

    r = http.post(f"{base_url}/ai/model/disease-detection", files=files, data=data)

    # Accept 200 (success) or 502 (model service unavailable in test environment)
    assert r.status_code in (200, 502), (
        f"Disease detection failed unexpectedly: {r.status_code} {r.text}"
    )

    if r.status_code == 200:
        response_json = r.json()

        # Verify response structure
        assert "model" in response_json, "Response missing 'model' field"
        assert "disease" in response_json, "Response missing 'disease' field"

        # Verify the plant is now marked as sick
        r = http.get(f"{base_url}/user/plants/sick")
        if r.status_code == 200:
            sick_plants = r.json()
            sick_plant_ids = [p.get("plant", {}).get("id") for p in sick_plants]
            assert plant_id in sick_plant_ids, (
                f"Plant {plant_id} should be marked as sick after disease detection"
            )

    # Cleanup
    http.delete(f"{base_url}/plant/delete/{plant_id}")


def test_disease_detection_with_family(user_token_and_session, base_url):
    """Verify disease detection accepts 'family' parameter."""
    access, http = user_token_and_session
    image_b64 = get_test_image_base64()

    # Create plant
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    assert r.status_code == 201
    plant_id = r.json()["id"]

    image_bytes = base64.b64decode(image_b64)
    files = {"image": ("test_plant.jpg", io.BytesIO(image_bytes), "image/jpeg")}

    # Send request with family parameter
    data = {
        "plant_id": plant_id,
        "family": "Rosaceae",
    }

    r = http.post(f"{base_url}/ai/model/disease-detection", files=files, data=data)

    # Should work same as simple test
    assert r.status_code in (200, 502)

    if r.status_code == 200:
        resp = r.json()
        assert "disease" in resp
        # Idealmente verificheremmo che la family sia davvero usata, ma è implementazione interna.

    http.delete(f"{base_url}/plant/delete/{plant_id}")


def test_disease_detection_with_threshold(user_token_and_session, base_url):
    """Verify disease detection accepts 'unknown_threshold' parameter."""
    access, http = user_token_and_session
    image_b64 = get_test_image_base64()

    # Create plant
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    assert r.status_code == 201
    plant_id = r.json()["id"]

    image_bytes = base64.b64decode(image_b64)
    files = {"image": ("test_plant.jpg", io.BytesIO(image_bytes), "image/jpeg")}

    # Send request with threshold
    data = {
        "plant_id": plant_id,
        "unknown_threshold": "0.8",
    }

    r = http.post(f"{base_url}/ai/model/disease-detection", files=files, data=data)

    assert r.status_code in (200, 502)

    if r.status_code == 200:
        resp = r.json()
        assert "disease" in resp

    http.delete(f"{base_url}/plant/delete/{plant_id}")


# ==========================================
# Cascade Delete Tests
# ==========================================


def _create_or_get_plant(http, base_url, must_create=False):
    """Helper to robustly create or reuse a plant THE USER OWNS."""
    import pytest
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    
    if r.status_code == 201:
        return r.json()["id"]
    
    if must_create:
        pytest.skip(f"Plant creation failed with {r.status_code} - skipping test")
    
    r = http.get(f"{base_url}/user_plant/all")
    if r.status_code == 200:
        user_plants = r.json()
        if user_plants:
            return user_plants[0]["id"]
    
    pytest.skip("Could not create or find a plant owned by user")


def test_delete_plant_cascades_plant_diseases(user_token_and_session, base_url):
    """
    Verify that deleting a plant also deletes its PlantDisease records.
    """
    access, http = user_token_and_session

    # Create a disease
    disease_name = f"TestDisease_{uuid.uuid4().hex[:6]}"
    r = http.post(f"{base_url}/disease/add", json={
        "name": disease_name,
        "description": "Test disease for cascade"
    })
    assert r.status_code == 201, f"disease/add failed: {r.text}"
    disease_id = r.json()["id"]

    # Create plant (must be fresh for cascade test)
    plant_id = _create_or_get_plant(http, base_url, must_create=True)

    # Link disease to plant
    r = http.post(f"{base_url}/plant_disease/add", json={
        "plant_id": plant_id,
        "disease_id": disease_id,
        "severity": 2,
        "notes": "Test link"
    })
    assert r.status_code in (200, 201), f"plant_disease/add failed: {r.text}"
    plant_disease_id = r.json().get("id")

    # Verify link exists
    r = http.get(f"{base_url}/plant_disease/all")
    assert r.status_code == 200
    links_before = [pd["id"] for pd in r.json()]
    assert plant_disease_id in links_before

    # Delete plant (should cascade)
    r = http.delete(f"{base_url}/plant/delete/{plant_id}")
    assert r.status_code == 204

    # Verify PlantDisease is gone
    r = http.get(f"{base_url}/plant_disease/all")
    assert r.status_code == 200
    links_after = [pd["id"] for pd in r.json()]
    assert plant_disease_id not in links_after, (
        f"CASCADE ERROR: PlantDisease {plant_disease_id} still exists after plant delete!"
    )

    # Cleanup disease
    http.delete(f"{base_url}/disease/delete/{disease_id}")

