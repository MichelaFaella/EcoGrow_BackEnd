# tests/test_validation.py
import uuid
import requests
from conftest import ensure_family, find_plant_id, get_test_image_base64


# ==========================================
# User Registration Validation Tests
# ==========================================

def test_user_add_invalid_email(base_url):
    """
    Verifica che /user/add rifiuti email vuota o con formato non valido.
    Endpoint: POST /user/add
    Required fields: email, password, first_name, last_name
    Expected: 400 per email vuota o malformata
    """
    http = requests.Session()
    
    # Email vuota
    r = http.post(f"{base_url}/user/add", json={
        "email": "",
        "password": "ValidPass123!",
        "first_name": "Test",
        "last_name": "User"
    })
    assert r.status_code == 400, f"Expected 400 for empty email, got {r.status_code}: {r.text}"
    
    # Email con formato non valido
    invalid_emails = [
        "not-an-email",
        "missing-at-sign.com",
        "@no-local-part.com",
    ]
    
    for bad_email in invalid_emails:
        r = http.post(f"{base_url}/user/add", json={
            "email": bad_email,
            "password": "ValidPass123!",
            "first_name": "Test",
            "last_name": "User"
        })
        assert r.status_code == 400, (
            f"Expected 400 for invalid email '{bad_email}', got {r.status_code}: {r.text}"
        )


def test_user_add_missing_required_fields(base_url):
    """
    Verifica che /user/add rifiuti richieste con campi obbligatori mancanti.
    Endpoint: POST /user/add
    Required fields: email, password (→ password_hash), first_name, last_name
    Expected: 400 con error message su campi mancanti
    """
    http = requests.Session()
    
    # Manca email
    r = http.post(f"{base_url}/user/add", json={
        "password": "ValidPass123!",
        "first_name": "Test",
        "last_name": "User"
    })
    assert r.status_code == 400, f"Expected 400 for missing email, got {r.status_code}: {r.text}"
    assert "email" in r.text.lower() or "mandatory" in r.text.lower()
    
    # Manca password
    email = f"nopass_{uuid.uuid4().hex[:6]}@test.com"
    r = http.post(f"{base_url}/user/add", json={
        "email": email,
        "first_name": "Test",
        "last_name": "User"
    })
    assert r.status_code == 400, f"Expected 400 for missing password, got {r.status_code}: {r.text}"
    
    # Manca first_name
    r = http.post(f"{base_url}/user/add", json={
        "email": f"nofirst_{uuid.uuid4().hex[:6]}@test.com",
        "password": "ValidPass123!",
        "last_name": "User"
    })
    assert r.status_code == 400, f"Expected 400 for missing first_name, got {r.status_code}: {r.text}"
    
    # Manca last_name
    r = http.post(f"{base_url}/user/add", json={
        "email": f"nolast_{uuid.uuid4().hex[:6]}@test.com",
        "password": "ValidPass123!",
        "first_name": "Test"
    })
    assert r.status_code == 400, f"Expected 400 for missing last_name, got {r.status_code}: {r.text}"


# ==========================================
# UUID Validation Tests
# ==========================================

def test_invalid_uuid_in_routes(user_token_and_session, base_url):
    """
    Verifica che le route rifiutino UUID non validi con 400.
    Endpoint testati:
    - POST /user_plant/add con plant_id non valido
    - PATCH /plant/update/<invalid> 
    - DELETE /plant/delete/<invalid>
    - POST /watering_plan/add con plant_id non valido
    Expected: 400 con "Invalid ... format"
    """
    access, http = user_token_and_session
    
    invalid_uuids = [
        "not-a-uuid",
        "12345",
        "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
        "",
    ]
    
    for bad_uuid in invalid_uuids:
        if bad_uuid:  # Skip empty string for path params
            # /plant/update/<invalid>
            r = http.patch(f"{base_url}/plant/update/{bad_uuid}", json={"size": "small"})
            assert r.status_code == 400, (
                f"Expected 400 for invalid plant_id '{bad_uuid}' in update, got {r.status_code}"
            )
            
            # /plant/delete/<invalid>
            r = http.delete(f"{base_url}/plant/delete/{bad_uuid}")
            assert r.status_code == 400, (
                f"Expected 400 for invalid plant_id '{bad_uuid}' in delete, got {r.status_code}"
            )
    
    # /user_plant/add con plant_id non valido nel body
    r = http.post(f"{base_url}/user_plant/add", json={"plant_id": "not-a-valid-uuid"})
    assert r.status_code == 400, f"Expected 400 for invalid plant_id in body, got {r.status_code}: {r.text}"
    
    # /watering_plan/add con plant_id non valido
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": "invalid-uuid-here",
        "next_due_at": "2030-01-01 08:00:00",
        "interval_days": 7
    })
    # Potrebbe essere 400 (UUID invalido) o 403 (non possiedi la pianta) a seconda dell'ordine di validazione
    assert r.status_code in (400, 403), (
        f"Expected 400/403 for invalid plant_id in watering_plan/add, got {r.status_code}"
    )


# ==========================================
# Plant Validation Tests
# ==========================================

def test_plant_add_missing_image(user_token_and_session, base_url):
    """
    Verifica che /plant/add rifiuti richieste senza il campo 'image'.
    Endpoint: POST /plant/add
    Required field: image (base64)
    Expected: 400 con "Field 'image' is required"
    """
    access, http = user_token_and_session
    
    # Senza campo image
    r = http.post(f"{base_url}/plant/add", json={})
    assert r.status_code == 400, f"Expected 400 for missing image, got {r.status_code}: {r.text}"
    assert "image" in r.text.lower()
    
    # Con campo image vuoto
    r = http.post(f"{base_url}/plant/add", json={"image": ""})
    assert r.status_code == 400, f"Expected 400 for empty image, got {r.status_code}: {r.text}"


def test_plant_add_invalid_base64(user_token_and_session, base_url):
    """
    Verifica che /plant/add rifiuti base64 non valido.
    Endpoint: POST /plant/add
    Expected: 400 con "Invalid base64 image data"
    """
    access, http = user_token_and_session
    
    r = http.post(f"{base_url}/plant/add", json={"image": "not-valid-base64!!!"})
    assert r.status_code == 400, f"Expected 400 for invalid base64, got {r.status_code}: {r.text}"


def test_plant_update_invalid_size(user_token_and_session, base_url):
    """
    Verifica che /plant/update rifiuti valori di size non ammessi.
    Endpoint: PATCH /plant/update/<plant_id>
    Allowed sizes: small, medium, large, giant
    Expected: 400 con errore su size
    """
    access, http = user_token_and_session
    
    # Prima creiamo una pianta valida
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    
    if r.status_code == 201:
        pid = r.json()["id"]
        
        # Prova ad aggiornare con size non valido
        r = http.patch(f"{base_url}/plant/update/{pid}", json={"size": "GIGANTIC"})
        assert r.status_code == 400, f"Expected 400 for invalid size, got {r.status_code}: {r.text}"
        
        r = http.patch(f"{base_url}/plant/update/{pid}", json={"size": "tiny"})
        assert r.status_code == 400, f"Expected 400 for invalid size 'tiny', got {r.status_code}"
        
        # Cleanup
        http.delete(f"{base_url}/plant/delete/{pid}")


# ==========================================
# Watering Validation Tests
# ==========================================

def test_watering_plan_missing_required_fields(user_token_and_session, base_url):
    """
    Verifica che /watering_plan/add rifiuti richieste con campi mancanti.
    Endpoint: POST /watering_plan/add
    Required fields: plant_id, next_due_at, interval_days
    Expected: 400 con "Campi obbligatori"
    """
    access, http = user_token_and_session
    
    # Manca plant_id
    r = http.post(f"{base_url}/watering_plan/add", json={
        "next_due_at": "2030-01-01 08:00:00",
        "interval_days": 7
    })
    assert r.status_code == 400, f"Expected 400 for missing plant_id, got {r.status_code}: {r.text}"
    
    # Manca next_due_at
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": "00000000-0000-0000-0000-000000000000",
        "interval_days": 7
    })
    assert r.status_code in (400, 403), f"Expected 400/403 for missing next_due_at, got {r.status_code}"
    
    # Manca interval_days
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": "00000000-0000-0000-0000-000000000000",
        "next_due_at": "2030-01-01 08:00:00"
    })
    assert r.status_code in (400, 403), f"Expected 400/403 for missing interval_days, got {r.status_code}"


def test_watering_log_missing_required_fields(user_token_and_session, base_url):
    """
    Verifica che /watering_log/add rifiuti richieste con campi mancanti.
    Endpoint: POST /watering_log/add
    Required fields: plant_id, amount_ml (done_at è opzionale, default = now)
    Expected: 400 con "Campi obbligatori"
    """
    access, http = user_token_and_session
    
    # Manca plant_id
    r = http.post(f"{base_url}/watering_log/add", json={
        "amount_ml": 200
    })
    assert r.status_code == 400, f"Expected 400 for missing plant_id, got {r.status_code}: {r.text}"
    
    # Manca amount_ml
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": "00000000-0000-0000-0000-000000000000"
    })
    assert r.status_code in (400, 403), f"Expected 400/403 for missing amount_ml, got {r.status_code}"


def test_validation_branches(user_token_and_session, base_url):
    """
    Test di validazione per watering_plan e watering_log.
    Usa /plant/add con image base64 per creare una pianta valida.
    """
    access, http = user_token_and_session

    # Crea una pianta valida con image
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    
    if r.status_code != 201:
        # Se PlantNet non è disponibile, skip questo test
        import pytest
        pytest.skip(f"Cannot create plant for validation test: {r.status_code} {r.text}")
    
    pid = r.json().get("id")
    assert pid, f"Plant created but no id returned: {r.json()}"

    # plan invalid datetime
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "not-a-date", "interval_days": 5
    })
    assert r.status_code in (400, 403, 422, 500), (
        f"Expected error for invalid datetime, got {r.status_code}: {r.text}"
    )

    # plan negative interval
    # Nota: /plant/add crea automaticamente un watering_plan, quindi
    # potremmo ottenere 409 (duplicato) invece di un errore di validazione
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": pid, "next_due_at": "2030-01-01 08:00:00", "interval_days": -1
    })
    assert r.status_code in (400, 403, 409, 422, 500), (
        f"Expected error for negative interval, got {r.status_code}: {r.text}"
    )

    # log invalid datetime
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": pid, "done_at": "not-a-date", "amount_ml": 100
    })
    assert r.status_code in (400, 403, 422, 500), (
        f"Expected error for invalid log datetime, got {r.status_code}: {r.text}"
    )

    # log negative amount - il backend DOVREBBE rifiutare valori negativi
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": pid, "done_at": "2030-01-01 09:00:00", "amount_ml": -50
    })
    assert r.status_code in (400, 422), (
        f"Expected 400/422 for negative amount_ml, got {r.status_code}: {r.text}"
    )
    
    # Cleanup
    http.delete(f"{base_url}/plant/delete/{pid}")

