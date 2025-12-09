# tests/test_shared_plant_from_image_sharing.py

import os
import uuid
import base64
import requests


def _create_user_and_login(base_url: str, email: str, password: str = "secret123"):
    """
    Crea un utente e fa il login, restituendo (access_token, user_id).
    """
    # create user (best effort)
    r = requests.post(
        f"{base_url}/user/add",
        json={
            "email": email,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    # se esiste già può dare 409, per il test va bene
    assert r.status_code in (201, 409), f"/user/add -> {r.status_code} {r.text}"

    # login
    r = requests.post(
        f"{base_url}/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, f"/auth/login -> {r.status_code} {r.text}"
    data = r.json()
    access = data.get("access_token")
    user_id = data.get("user_id")
    assert access and user_id, "Missing access_token or user_id from /auth/login"
    return access, user_id


def _load_test_image_base64() -> str:
    """
    Carica l'immagine di test dalla cartella tests e la restituisce in base64.

    Cerca file come:
    - test-plant.jpg 
    - test_plant.jpeg
    - test_plant.jpg
    - test-plant.jpeg
    nella stessa cartella di questo test.
    """
    tests_dir = os.path.dirname(__file__)

    candidates = [
        "test-plant.jpg",
        "test_plant.jpeg",
        "test_plant.jpg",
        "test-plant.jpeg",
    ]

    image_path = None
    for name in candidates:
        candidate = os.path.join(tests_dir, name)
        if os.path.exists(candidate):
            image_path = candidate
            break

    assert image_path, (
        "Immagine di test non trovata: atteso un file tipo "
        "'test-plant.jpg' o 'test_plant.jpeg' nella cartella tests."
    )

    with open(image_path, "rb") as f:
        raw = f.read()

    return base64.b64encode(raw).decode("ascii")


def test_shared_plant_flow_from_image(user_token_and_session, base_url):
    """
    Flusso completo:

    1. Utente owner (dal fixture) è loggato.
    2. Creo un secondo utente e faccio login, ricavando il suo short_id.
    3. Creo una pianta da immagine (endpoint /plant/add con campo 'image' base64).
    4. Primo sharing (owner -> recipient) /shared_plant/add.
    5. Secondo sharing immediato con stessi dati → 409 Already shared.
    6. Termino lo sharing /shared_plant/delete/<first_shared_id>.
    7. Ripeto lo sharing con stessi owner/recipient/plant → 201 OK.
    8. CLEANUP:
       - termino anche la seconda condivisione
       - cancello la pianta
       - cancello il secondo utente dal DB (/user/delete-me)
    """

    # --- 1. Owner: riuso il fixture che crea utente+login e setta l'Authorization ---
    access_owner, http_owner = user_token_and_session

    # --- 2. Creo secondo utente e ottengo il suo short_id ---
    recipient_email = f"recipient_{uuid.uuid4().hex[:8]}@example.com"
    recipient_token, recipient_user_id = _create_user_and_login(base_url, recipient_email)
    short_id = recipient_user_id.split("-")[0]
    assert short_id, "short_id del recipient non ricavato correttamente"

    # --- 3. Creo una pianta a partire dall'immagine, usando /plant/add con base64 ---
    image_b64 = _load_test_image_base64()
    r = http_owner.post(f"{base_url}/plant/add", json={"image": image_b64})
    assert r.status_code == 201, f"/plant/add from image -> {r.status_code} {r.text}"
    plant_id = r.json().get("id")
    assert plant_id, f"ID pianta mancante nella risposta di /plant/add: {r.text}"

    # --- 4. Primo sharing owner -> recipient ---
    payload = {"plant_id": plant_id, "short_id": short_id}
    r = http_owner.post(f"{base_url}/shared_plant/add", json=payload)
    assert r.status_code == 201, f"Primo /shared_plant/add -> {r.status_code} {r.text}"
    first_shared_id = r.json().get("shared_id")
    assert first_shared_id, f"shared_id mancante nella risposta: {r.text}"

    # Verifico che la condivisione risulti attiva tra quelle dell'owner
    r = http_owner.get(f"{base_url}/shared_plant/all")
    assert r.status_code == 200, f"/shared_plant/all -> {r.status_code} {r.text}"
    rows = r.json()
    assert any(sp["shared_id"] == first_shared_id for sp in rows), (
        "La condivisione appena creata non compare in /shared_plant/all"
    )

    # --- 5. Secondo sharing immediato con gli stessi parametri deve dare 409 Already shared ---
    r = http_owner.post(f"{base_url}/shared_plant/add", json=payload)
    assert r.status_code == 409, (
        f"Secondo /shared_plant/add con condivisione ancora attiva dovrebbe "
        f"restituire 409, ma è {r.status_code} {r.text}"
    )

    # --- 6. Termino il primo sharing (soft delete) ---
    r = http_owner.delete(f"{base_url}/shared_plant/delete/{first_shared_id}")
    assert r.status_code == 204, (
        f"/shared_plant/delete/{first_shared_id} -> {r.status_code} {r.text}"
    )

    # Dopo il delete, /shared_plant/all non deve più mostrare questa condivisione attiva
    r = http_owner.get(f"{base_url}/shared_plant/all")
    assert r.status_code == 200, f"/shared_plant/all post-delete -> {r.status_code} {r.text}"
    rows = r.json()
    assert all(sp["shared_id"] != first_shared_id for sp in rows), (
        "La condivisione terminata è ancora presente tra quelle attive"
    )

    # --- 7. Nuovo sharing con stesso owner, stesso recipient e stessa pianta ---
    r = http_owner.post(f"{base_url}/shared_plant/add", json=payload)
    assert r.status_code == 201, (
        "Dopo aver terminato la condivisione, /shared_plant/add con gli stessi "
        f"parametri dovrebbe tornare 201, ma è {r.status_code} {r.text}"
    )
    second_shared_id = r.json().get("shared_id")
    assert second_shared_id and second_shared_id != first_shared_id, (
        "La nuova condivisione dovrebbe avere un nuovo shared_id distinto da quella terminata"
    )

    # ----------------------------------------------------------------------
    # 8. CLEANUP: termino tutto quello che ho appena creato
    # ----------------------------------------------------------------------

    # 8.1 Termino anche la seconda condivisione (così non resta nulla di attivo)
    r = http_owner.delete(f"{base_url}/shared_plant/delete/{second_shared_id}")
    assert r.status_code == 204, (
        f"/shared_plant/delete/{second_shared_id} (cleanup) -> "
        f"{r.status_code} {r.text}"
    )

    # 8.2 Cancello la pianta creata
    r = http_owner.delete(f"{base_url}/plant/delete/{plant_id}")
    assert r.status_code == 204, (
        f"/plant/delete/{plant_id} (cleanup) -> {r.status_code} {r.text}"
    )

    # 8.3 Cancello il secondo utente usando il suo token (/user/delete-me)
    recipient_http = requests.Session()
    recipient_http.headers["Authorization"] = f"Bearer {recipient_token}"
    r = recipient_http.delete(f"{base_url}/user/delete-me")
    assert r.status_code == 204, (
        f"/user/delete-me (cleanup recipient) -> {r.status_code} {r.text}"
    )
