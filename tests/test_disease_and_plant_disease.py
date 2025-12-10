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
        "scientific_name": sci, "common_name": "DZHost",
        "use": "ornamental","water_level": 2,"light_level": 3,"difficulty": 2,
        "min_temp_c": 10,"max_temp_c": 25,"category": "test","climate": "temperate","size": "medium",
        "family_id": fam_id,
        "image": image_b64
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        # If it failed, check if it was a conflict (already exists) or something else
        # If something else, fail here with the error
        if r.status_code != 409:
             assert r.status_code == 201, f"plant/add failed: {r.text}"
        pid = find_plant_id(http, base_url, sci)
    
    assert pid, f"Could not find or create plant with scientific_name={sci}"

    # possiedo la plant (richiesto da alcune route)
    http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})

    # link plant_disease
    r = http.post(f"{base_url}/plant_disease/add",
                  json={"plant_id": pid, "disease_id": dis_id, "severity": 2, "notes": "leaf spots"})
    assert r.status_code in (201, 200), r.text
    pd_id = r.json().get("id")
    assert pd_id

    # update link
    r = http.patch(f"{base_url}/plant_disease/update/{pd_id}", json={"severity": 3, "status": "treated"})
    assert r.status_code == 200

    # cleanup link e disease
    r = http.delete(f"{base_url}/plant_disease/delete/{pd_id}")
    assert r.status_code == 204
    r = http.delete(f"{base_url}/disease/delete/{dis_id}")
    assert r.status_code == 204


import uuid
from conftest import ensure_family, find_plant_id

def test_disease_and_plant_disease_extended(user_token_and_session, base_url):
    access, http = user_token_and_session

    # create disease
    name = f"LeafRust_{uuid.uuid4().hex[:6]}"
    r = http.post(f"{base_url}/disease/add", json={"name": name, "description": "fungal"})
    assert r.status_code == 201, r.text
    dis_id = r.json()["id"]

    # ensure mapped plant and ownership
    SPECIES = "Adiantum raddianum"
    FAMILY  = "Polypodiaceae"
    ensure_family(http, base_url, FAMILY)
    r = http.post(f"{base_url}/plant/add", json={
        "scientific_name": SPECIES, "common_name": "Maidenhair fern",
        "use": "ornamental","water_level": 3,"light_level": 3,"difficulty": 3,
        "min_temp_c": 15,"max_temp_c": 28,"category": "fern","climate": "tropical","size": "small"
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        pid = find_plant_id(http, base_url, SPECIES)
    assert pid

    # make sure user owns the plant (some APIs require ownership for relations)
    http.post(f"{base_url}/user_plant/add", json={"plant_id": pid})

    # link plant_disease
    r = http.post(f"{base_url}/plant_disease/add",
                  json={"plant_id": pid, "disease_id": dis_id, "severity": 2, "notes": "leaf spots"})
    assert r.status_code in (201, 200), r.text
    pd_id = r.json().get("id")
    assert pd_id

    # update
    r = http.patch(f"{base_url}/plant_disease/update/{pd_id}", json={"severity": 3, "status": "treated"})
    assert r.status_code == 200


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
        "family": "Rosaceae"
    }

    r = http.post(f"{base_url}/ai/model/disease-detection", files=files, data=data)
    
    # Should work same as simple test
    assert r.status_code in (200, 502)
    
    if r.status_code == 200:
        resp = r.json()
        assert "disease" in resp
        # Ideally we'd verify the family was used by the model, but that might be internal.
        # At least we verify it didn't crash.

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
        "unknown_threshold": "0.8"
    }

    r = http.post(f"{base_url}/ai/model/disease-detection", files=files, data=data)
    
    assert r.status_code in (200, 502)
    
    if r.status_code == 200:
        resp = r.json()
        assert "disease" in resp

    http.delete(f"{base_url}/plant/delete/{plant_id}")