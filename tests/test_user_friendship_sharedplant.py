# tests/test_user_friendship_sharedplant.py
import uuid
import requests
from conftest import ensure_family, find_plant_id, get_test_image_base64


def _get_short_id(user_id: str) -> str:
    """
    Ricava lo short_id a partire dallo user_id (prima parte dell'UUID).
    """
    return user_id.split("-")[0]


def test_user_friendship_sharedplant(user_token_and_session, base_url):
    access, http = user_token_and_session

    # creo un secondo utente
    email = f"u_{uuid.uuid4().hex[:6]}@test.local"
    r = http.post(
        f"{base_url}/user/add",
        json={
            "email": email,
            "password": "Abc!2345",
            "first_name": "Guest",
            "last_name": "Two",
        },
    )
    assert r.status_code == 201, r.text
    uid2 = r.json()["id"]
    short_id_2 = _get_short_id(uid2)

    # login come secondo utente e aggiorno il profilo usando /user/update (senza id)
    http2 = requests.Session()
    r_login = http2.post(
        f"{base_url}/auth/login",
        json={"email": email, "password": "Abc!2345"},
    )
    assert r_login.status_code == 200, f"/auth/login (second user) -> {r_login.status_code} {r_login.text}"
    token2 = r_login.json()["access_token"]
    http2.headers["Authorization"] = f"Bearer {token2}"

    r = http2.patch(
        f"{base_url}/user/update",
        json={"first_name": "GuestUpd"},
    )
    assert r.status_code == 200

    # creo una pianta "condivisibile" (con family + image)
    sci = f"ShareMe {uuid.uuid4().hex[:6]}"
    fam_id = ensure_family(http, base_url, "Testaceae")
    image_b64 = get_test_image_base64()

    r = http.post(
        f"{base_url}/plant/add",
        json={
            "scientific_name": sci,
            "common_name": "SharePlant",
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
        },
    )
    if r.status_code == 201:
        pid = r.json()["id"]
    else:
        pid = find_plant_id(http, base_url, sci)
    assert pid

    # mio user_id (owner)
    me = http.get(f"{base_url}/check-auth").json()["user_id"]

    # friendship con i campi attesi dal backend (richiede anche 'status')
    r = http.post(
        f"{base_url}/friendship/add",
        json={"user_id_a": me, "user_id_b": uid2, "status": "pending"},
    )
    assert r.status_code in (200, 201), r.text
    fid = r.json()["id"]

    # cambio di stato
    r = http.patch(
        f"{base_url}/friendship/update/{fid}",
        json={"status": "accepted"},
    )
    assert r.status_code == 200

    # shared_plant: API attuale richiede plant_id + short_id
    r = http.post(
        f"{base_url}/shared_plant/add",
        json={
            "plant_id": pid,
            "short_id": short_id_2,
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    sid = body.get("shared_id") or body.get("id")
    assert sid, f"SharedPlant id non trovato in risposta: {body}"

    r = http.patch(
        f"{base_url}/shared_plant/update/{sid}",
        json={"note": "handle with care"},
    )
    assert r.status_code == 200

    # cleanup minimi
    assert http.delete(f"{base_url}/shared_plant/delete/{sid}").status_code == 204
    assert http.delete(f"{base_url}/friendship/delete/{fid}").status_code == 204

    # cancellazione del secondo utente: va fatto con il SUO token via /user/delete-me
    r = http2.delete(f"{base_url}/user/delete-me")
    assert r.status_code == 204, f"/user/delete-me (second user) -> {r.status_code} {r.text}"


def test_friendship_shared_plant_extended(user_token_and_session, base_url):
    access, http = user_token_and_session

    # crea un secondo utente (idempotente: se 409/500, prendi l'ultimo)
    email = f"friend_{uuid.uuid4().hex[:6]}@example.com"
    r = http.post(
        f"{base_url}/user/add",
        json={
            "email": email,
            "password": "Abc!2345",
            "first_name": "Friend",
            "last_name": "User",
        },
    )
    if r.status_code == 201:
        uid2 = r.json().get("id")
    else:
        all_users = http.get(f"{base_url}/user/all").json()
        uid2 = all_users[-1]["id"]
    short_id_2 = _get_short_id(uid2)

    # my user_id
    me = http.get(f"{base_url}/check-auth").json().get("user_id")
    assert me

    # friendship: il backend richiede 'user_id_a','user_id_b' **e** 'status'
    r = http.post(
        f"{base_url}/friendship/add",
        json={"user_id_a": me, "user_id_b": uid2, "status": "pending"},
    )
    assert r.status_code in (200, 201), f"friendship add failed: {r.status_code} {r.text}"
    fid = r.json()["id"]

    # update status → accepted, poi blocked (copriamo due rami)
    for status in ("accepted", "blocked"):
        r = http.patch(
            f"{base_url}/friendship/update/{fid}",
            json={"status": status},
        )
        assert r.status_code == 200

    # ensure a plant e condividila (family + image)
    SPECIES = "Aeschynanthus lobianus"
    FAMILY = "Gesneriaceae"
    fam_id = ensure_family(http, base_url, FAMILY)
    image_b64 = get_test_image_base64()

    r = http.post(
        f"{base_url}/plant/add",
        json={
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
        },
    )
    if r.status_code == 201:
        pid = r.json().get("id")
    else:
        pid = find_plant_id(http, base_url, SPECIES)
    assert pid

    # shared_plant: API attuale → plant_id + short_id
    r = http.post(
        f"{base_url}/shared_plant/add",
        json={
            "plant_id": pid,
            "short_id": short_id_2,
        },
    )
    assert r.status_code in (200, 201), f"shared_plant add failed: {r.status_code} {r.text}"
    body = r.json()
    sid = body.get("shared_id") or body.get("id")
    assert sid, f"SharedPlant id non trovato in risposta: {body}"

    r = http.patch(
        f"{base_url}/shared_plant/update/{sid}",
        json={"note": "handle with care"},
    )
    assert r.status_code == 200
