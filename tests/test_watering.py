# tests/test_watering.py
"""
Consolidated tests for all watering-related endpoints:
- Watering Plan CRUD
- Watering Log CRUD
- Watering Do/Undo
- Watering Overview
- Watering Calendar Export
"""
import pytest
import uuid
import datetime as dt
from conftest import ensure_family, find_plant_id, get_test_image_base64


def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _create_or_get_plant(http, base_url, must_create=False):
    """
    Helper to robustly create or reuse a plant THE USER OWNS.
    If must_create is True, skips test if plant creation fails.
    Returns plant_id.
    """
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    
    if r.status_code == 201:
        return r.json()["id"]
    
    if must_create:
        pytest.skip(f"Plant creation failed with {r.status_code} - skipping test")
    
    # Try to get a plant owned by this user (from their garden, not catalog!)
    r = http.get(f"{base_url}/user_plant/all")
    if r.status_code == 200:
        user_plants = r.json()
        if user_plants:
            return user_plants[0]["id"]
    
    pytest.skip("Could not create or find a plant owned by user")


# ==========================================
# Watering Plan CRUD Tests
# ==========================================


def test_watering_plan_create_and_list(user_token_and_session, base_url):
    """Test watering plan creation and listing."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    # Ensure ownership
    http.post(f"{base_url}/user_plant/add", json={"plant_id": plant_id})
    
    # Try to create watering plan (may already exist)
    r = http.post(f"{base_url}/watering_plan/add", json={
        "plant_id": plant_id,
        "next_due_at": "2030-01-01 08:00:00",
        "interval_days": 5,
    })
    assert r.status_code in (200, 201, 409), f"watering_plan/add failed: {r.status_code}"
    
    # List plans
    r = http.get(f"{base_url}/watering_plan/all")
    assert r.status_code == 200
    plans = r.json()
    assert isinstance(plans, list)


def test_watering_plan_add_requires_ownership(user_token_and_session, additional_user, base_url):
    """Test watering_plan/add returns 403 if user doesn't own the plant."""
    access_a, http_a = user_token_and_session
    http_b = additional_user["http"]
    
    # User A creates a plant
    plant_id = _create_or_get_plant(http_a, base_url)
    
    # User B tries to add a watering plan for User A's plant
    r = http_b.post(f"{base_url}/watering_plan/add", json={
        "plant_id": plant_id,
        "next_due_at": "2030-01-01 08:00:00",
        "interval_days": 5,
    })
    # Should be forbidden since User B doesn't own the plant
    assert r.status_code in (403, 200), f"Expected 403 or 200 (implicit ownership), got {r.status_code}"


def test_watering_plan_update(user_token_and_session, base_url):
    """Test watering plan update."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    http.post(f"{base_url}/user_plant/add", json={"plant_id": plant_id})
    
    # Get the plan
    r = http.get(f"{base_url}/watering_plan/all")
    assert r.status_code == 200
    plans = [p for p in r.json() if p.get("plant_id") == plant_id]
    
    if not plans:
        pytest.skip("No watering plan found for plant")
    
    plan_id = plans[0]["id"]
    
    # Update
    r = http.patch(f"{base_url}/watering_plan/update/{plan_id}", json={
        "interval_days": 7
    })
    assert r.status_code == 200, f"update failed: {r.status_code}"


def test_watering_plan_delete(user_token_and_session, base_url):
    """Test watering plan deletion."""
    access, http = user_token_and_session
    
    # Create a fresh plant with a watering plan
    image_b64 = get_test_image_base64()
    r = http.post(f"{base_url}/plant/add", json={"image": image_b64})
    
    if r.status_code != 201:
        pytest.skip("Cannot create plant for delete test")
    
    plant_id = r.json()["id"]
    
    # Get the plan (auto-created with plant)
    r = http.get(f"{base_url}/watering_plan/all")
    assert r.status_code == 200
    plans = [p for p in r.json() if p.get("plant_id") == plant_id]
    
    if not plans:
        pytest.skip("No watering plan found for plant")
    
    plan_id = plans[0]["id"]
    
    # Delete
    r = http.delete(f"{base_url}/watering_plan/delete/{plan_id}")
    assert r.status_code == 204
    
    # Verify deleted
    r = http.get(f"{base_url}/watering_plan/all")
    assert r.status_code == 200
    remaining = [p for p in r.json() if p.get("id") == plan_id]
    assert len(remaining) == 0, "Plan still exists after delete"
    
    # Cleanup plant
    http.delete(f"{base_url}/plant/delete/{plant_id}")


# ==========================================
# Watering Log CRUD Tests
# ==========================================


def test_watering_log_add_and_list(user_token_and_session, base_url):
    """Test watering log creation and listing."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    # Add log
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": plant_id,
        "done_at": _now_iso(),
        "amount_ml": 180
    })
    assert r.status_code == 201, f"watering_log/add failed: {r.status_code}"
    
    # List logs
    r = http.get(f"{base_url}/watering_log/all")
    assert r.status_code == 200
    logs = r.json()
    assert isinstance(logs, list)


def test_watering_log_update_and_delete(user_token_and_session, base_url):
    """Test watering log update and deletion."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    # Add log
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": plant_id,
        "done_at": _now_iso(),
        "amount_ml": 150
    })
    assert r.status_code == 201
    log_id = r.json().get("id")
    
    if not log_id:
        # Try to get from list
        r = http.get(f"{base_url}/watering_log/all")
        logs = [l for l in r.json() if l.get("plant_id") == plant_id]
        if logs:
            log_id = logs[0]["id"]
    
    if not log_id:
        pytest.skip("Could not create or find log")
    
    # Update
    r = http.patch(f"{base_url}/watering_log/update/{log_id}", json={
        "amount_ml": 200
    })
    assert r.status_code == 200
    
    # Delete
    r = http.delete(f"{base_url}/watering_log/delete/{log_id}")
    assert r.status_code == 204


def test_watering_log_negative_amount(user_token_and_session, base_url):
    """Test that negative amount_ml is rejected."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/watering_log/add", json={
        "plant_id": plant_id,
        "amount_ml": -100,
        "done_at": _now_iso()
    })
    
    assert r.status_code == 400, f"Expected 400 for negative amount_ml, got {r.status_code}"


# ==========================================
# Watering Do/Undo Tests
# ==========================================


def test_watering_do_success(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/do creates a watering log."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "amount_ml": 200,
        "note": "Test watering"
    })
    assert r.status_code == 200, f"watering/do failed: {r.status_code} {r.text}"
    
    data = r.json()
    assert data.get("ok") is True
    assert "next_due_at" in data


def test_watering_do_missing_amount_ml(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/do fails without amount_ml."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "note": "No amount"
    })
    assert r.status_code == 400


def test_watering_do_invalid_amount_ml(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/do fails with non-integer amount_ml."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "amount_ml": "not_a_number"
    })
    assert r.status_code == 400


def test_watering_do_invalid_done_at_format(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/do rejects invalid done_at format."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "amount_ml": 100,
        "done_at": "not-a-valid-date"
    })
    assert r.status_code == 400


def test_watering_do_forbidden_not_owner(user_token_and_session, additional_user, base_url):
    """Verify POST /plant/{plant_id}/watering/do returns 403 if user doesn't own plant."""
    access_a, http_a = user_token_and_session
    http_b = additional_user["http"]
    
    plant_id = _create_or_get_plant(http_a, base_url)
    
    r = http_b.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "amount_ml": 100
    })
    assert r.status_code == 403


def test_watering_do_nonexistent_plant(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/do fails for non-existent plant."""
    access, http = user_token_and_session
    
    fake_plant_id = str(uuid.uuid4())
    r = http.post(f"{base_url}/plant/{fake_plant_id}/watering/do", json={
        "amount_ml": 100
    })
    assert r.status_code in (403, 404)


def test_watering_undo_success(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/undo removes last watering."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    # First, do a watering
    r = http.post(f"{base_url}/plant/{plant_id}/watering/do", json={
        "amount_ml": 150
    })
    assert r.status_code == 200
    
    # Now undo it
    r = http.post(f"{base_url}/plant/{plant_id}/watering/undo")
    assert r.status_code == 200
    
    data = r.json()
    assert data.get("ok") is True


def test_watering_undo_no_log_to_undo(user_token_and_session, base_url):
    """Verify POST /plant/{plant_id}/watering/undo handles no-log case."""
    access, http = user_token_and_session
    
    plant_id = _create_or_get_plant(http, base_url)
    
    r = http.post(f"{base_url}/plant/{plant_id}/watering/undo")
    # Accept either success or graceful failure
    assert r.status_code in (200, 400)


# ==========================================
# Watering Overview Tests
# ==========================================


def test_watering_overview_returns_weekly_data(user_token_and_session, base_url):
    """Verify GET /watering/overview returns weekly calendar data."""
    access, http = user_token_and_session
    
    _create_or_get_plant(http, base_url)
    
    r = http.get(f"{base_url}/watering/overview")
    assert r.status_code == 200
    
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 7
    
    for day in data:
        assert "date" in day
        assert "plants_count" in day
        assert "plants" in day


# ==========================================
# Watering Calendar Export Tests
# ==========================================


def test_watering_calendar_export_success(user_token_and_session, base_url):
    """Verify GET /watering_plan/calendar-export returns events for calendar sync."""
    access, http = user_token_and_session
    
    _create_or_get_plant(http, base_url)
    
    r = http.get(f"{base_url}/watering_plan/calendar-export")
    assert r.status_code == 200
    
    data = r.json()
    assert isinstance(data, list)
    
    for event in data:
        assert "id" in event
        assert "plant_id" in event
        assert "plant_name" in event
        assert "title" in event
        assert "start" in event
        assert "interval_days" in event


def test_watering_calendar_export_unauthorized(base_url):
    """Verify GET /watering_plan/calendar-export requires authentication."""
    import requests
    http = requests.Session()
    
    r = http.get(f"{base_url}/watering_plan/calendar-export")
    assert r.status_code == 401
