# tests/test_family_crud.py
import uuid

def test_family_crud(user_token_and_session, base_url):
    access, http = user_token_and_session

    name = f"Fam_{uuid.uuid4().hex[:8]}"
    r = http.post(f"{base_url}/family/add", json={"name": name, "description": "tmp fam"})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    r = http.patch(f"{base_url}/family/update/{fid}", json={"description": "updated"})
    assert r.status_code == 200

    r = http.delete(f"{base_url}/family/delete/{fid}")
    assert r.status_code == 204
