# tests/test_reminders.py
"""
Consolidated tests for all reminder-related endpoints:
- Reminder CRUD (add, update, list, delete)
- Reminder isolation between users
- Reminder cascade delete with plants
- Plant-specific reminders
"""
import pytest
import uuid
import datetime as dt
from conftest import get_test_image_base64


def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _create_or_get_plant(http, base_url, must_create=False):
    """Helper to robustly create or reuse a plant THE USER OWNS."""
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


# ==========================================
# Reminder CRUD Tests
# ==========================================


def test_reminder_add(user_token_and_session, base_url):
    """Test reminder creation."""
    access, http = user_token_and_session
    
    r = http.post(f"{base_url}/reminder/add", json={
        "title": "Test reminder",
        "scheduled_at": "2030-03-01 08:00:00"
    })
    assert r.status_code == 201, f"reminder/add failed: {r.text}"
    
    rid = r.json().get("id")
    assert rid
    
    # Cleanup
    http.delete(f"{base_url}/reminder/delete/{rid}")


def test_reminder_list_all(user_token_and_session, base_url):
    """Test listing all reminders."""
    access, http = user_token_and_session
    
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    
    data = r.json()
    assert isinstance(data, list)


def test_reminder_update(user_token_and_session, base_url):
    """Test reminder update."""
    access, http = user_token_and_session
    
    # Create reminder
    r = http.post(f"{base_url}/reminder/add", json={
        "title": "Original title",
        "scheduled_at": "2030-03-01 08:00:00"
    })
    assert r.status_code == 201
    rid = r.json()["id"]
    
    # Update
    r = http.patch(f"{base_url}/reminder/update/{rid}", json={
        "title": "Updated title"
    })
    assert r.status_code == 200
    
    # Cleanup
    http.delete(f"{base_url}/reminder/delete/{rid}")


def test_reminder_delete(user_token_and_session, base_url):
    """Test reminder deletion."""
    access, http = user_token_and_session
    
    # Create reminder
    r = http.post(f"{base_url}/reminder/add", json={
        "title": "To be deleted",
        "scheduled_at": "2030-03-01 08:00:00"
    })
    assert r.status_code == 201
    rid = r.json()["id"]
    
    # Delete
    r = http.delete(f"{base_url}/reminder/delete/{rid}")
    assert r.status_code == 204
    
    # Verify deleted
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    assert rid not in [rem["id"] for rem in r.json()]


def test_reminder_add_missing_fields(user_token_and_session, base_url):
    """Test reminder creation fails without required fields."""
    access, http = user_token_and_session
    
    # Missing title
    r = http.post(f"{base_url}/reminder/add", json={
        "scheduled_at": "2030-03-01 08:00:00"
    })
    assert r.status_code == 400
    
    # Missing scheduled_at
    r = http.post(f"{base_url}/reminder/add", json={
        "title": "Test"
    })
    assert r.status_code == 400


# ==========================================
# Reminder Isolation Tests
# ==========================================


def test_user_cannot_view_other_user_reminders(user_token_and_session, additional_user, base_url):
    """Verify that User B cannot see User A's reminders."""
    access_a, http_a = user_token_and_session
    http_b = additional_user["http"]
    
    # User A creates a reminder
    r = http_a.post(f"{base_url}/reminder/add", json={
        "title": "User A's private reminder",
        "scheduled_at": "2030-05-01 10:00:00"
    })
    assert r.status_code == 201
    reminder_id_a = r.json()["id"]
    
    # User B lists their reminders
    r = http_b.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    reminder_ids_b = [rem["id"] for rem in r.json()]
    
    # User A's reminder should NOT be visible to User B
    assert reminder_id_a not in reminder_ids_b, "User B can see User A's reminder!"
    
    # Cleanup
    http_a.delete(f"{base_url}/reminder/delete/{reminder_id_a}")


def test_user_cannot_delete_other_user_reminder(user_token_and_session, additional_user, base_url):
    """Verify that User B cannot delete User A's reminder."""
    access_a, http_a = user_token_and_session
    http_b = additional_user["http"]
    
    # User A creates a reminder
    r = http_a.post(f"{base_url}/reminder/add", json={
        "title": "User A's protected reminder",
        "scheduled_at": "2030-06-01 10:00:00"
    })
    assert r.status_code == 201
    reminder_id_a = r.json()["id"]
    
    # User B tries to delete User A's reminder
    r = http_b.delete(f"{base_url}/reminder/delete/{reminder_id_a}")
    assert r.status_code == 403, f"User B can delete User A's reminder! Status: {r.status_code}"
    
    # Verify reminder still exists for User A
    r = http_a.get(f"{base_url}/reminder/all")
    assert reminder_id_a in [rem["id"] for rem in r.json()]
    
    # Cleanup
    http_a.delete(f"{base_url}/reminder/delete/{reminder_id_a}")


def test_user_cannot_update_other_user_reminder(user_token_and_session, additional_user, base_url):
    """Verify that User B cannot update User A's reminder."""
    access_a, http_a = user_token_and_session
    http_b = additional_user["http"]
    
    # User A creates a reminder
    r = http_a.post(f"{base_url}/reminder/add", json={
        "title": "Original title by A",
        "scheduled_at": "2030-07-01 10:00:00"
    })
    assert r.status_code == 201
    reminder_id_a = r.json()["id"]
    
    # User B tries to update
    r = http_b.patch(f"{base_url}/reminder/update/{reminder_id_a}", json={
        "title": "Hacked by B"
    })
    assert r.status_code == 403, f"User B can update User A's reminder!"
    
    # Cleanup
    http_a.delete(f"{base_url}/reminder/delete/{reminder_id_a}")


# ==========================================
# Plant-Specific Reminders Tests
# ==========================================


def test_get_reminders_for_plant(user_token_and_session, base_url):
    """Test GET /plant/{plant_id}/reminders returns plant-specific reminders."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.get(f"{base_url}/plant/{plant_id}/reminders")
    assert r.status_code == 200
    
    data = r.json()
    assert isinstance(data, list)


# ==========================================
# Cascade Delete Tests
# ==========================================


def test_delete_plant_cascades_reminders(user_token_and_session, base_url):
    """
    Verify that deleting a plant also deletes its associated reminders.
    Note: This tests the manual cascade in delete_plant, not DB cascade.
    """
    access, http = user_token_and_session
    
    # Create plant (must be fresh for cascade test)
    plant_id = _create_or_get_plant(http, base_url, must_create=True)
    
    # Do a watering to potentially create a reminder
    http.post(f"{base_url}/plant/{plant_id}/watering/do", json={"amount_ml": 100})
    
    # Get all reminders before delete
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    reminders_before = r.json()
    plant_reminder_ids = [
        rem["id"] for rem in reminders_before 
        if rem.get("entity_id") == plant_id and rem.get("entity_type") == "plant"
    ]
    
    # Delete plant (should cascade)
    r = http.delete(f"{base_url}/plant/delete/{plant_id}")
    assert r.status_code == 204
    
    # Verify reminders are gone
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    reminders_after = r.json()
    remaining_ids = [rem["id"] for rem in reminders_after]
    
    for rid in plant_reminder_ids:
        assert rid not in remaining_ids, f"Reminder {rid} still exists after plant delete!"


# ==========================================
# Authorization Tests
# ==========================================


def test_reminder_endpoints_require_auth(base_url):
    """Verify reminder endpoints require authentication."""
    import requests
    http = requests.Session()
    
    # All should return 401
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 401
    
    r = http.post(f"{base_url}/reminder/add", json={"title": "test"})
    assert r.status_code == 401
    
    r = http.delete(f"{base_url}/reminder/delete/{uuid.uuid4()}")
    assert r.status_code == 401
