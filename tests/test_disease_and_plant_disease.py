# tests/test_disease_and_plant_disease.py
import uuid
from conftest import ensure_family, find_plant_id

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
    r = http.post(f"{base_url}/plant/add", json={
        "scientific_name": sci, "common_name": "DZHost",
        "use": "ornamental","water_level": 2,"light_level": 3,"difficulty": 2,
        "min_temp_c": 10,"max_temp_c": 25,"category": "test","climate": "temperate","size": "medium",
        "family_id": fam_id
    })
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        pid = find_plant_id(http, base_url, sci)

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