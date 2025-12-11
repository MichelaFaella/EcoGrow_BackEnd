# tests/test_questionnaire.py
"""
Tests for questionnaire endpoints:
- GET /questionnaire/questions (get questions for user)
- POST /questionnaire/answers (submit answers)
"""
import pytest
import uuid


# ==========================================
# GET /questionnaire/questions
# ==========================================


def test_questionnaire_get_questions(user_token_and_session, base_url):
    """
    Verify GET /questionnaire/questions returns questions.
    
    Endpoint: GET /questionnaire/questions
    Expected: 200 with list of questions (may be empty if none defined)
    """
    access, http = user_token_and_session

    r = http.get(f"{base_url}/questionnaire/questions")
    assert r.status_code == 200, f"questionnaire/questions failed: {r.status_code} {r.text}"
    
    data = r.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"


def test_questionnaire_get_questions_unauthorized(base_url):
    """
    Verify GET /questionnaire/questions requires authentication.
    
    Expected: 401 Unauthorized
    """
    import requests
    http = requests.Session()
    
    r = http.get(f"{base_url}/questionnaire/questions")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ==========================================
# POST /questionnaire/answers
# ==========================================


def test_questionnaire_submit_empty_answers(user_token_and_session, base_url):
    """
    Verify POST /questionnaire/answers rejects empty answers object.
    
    Endpoint: POST /questionnaire/answers
    Request body: { "answers": {} }
    Expected: 400 with error message
    """
    access, http = user_token_and_session

    r = http.post(f"{base_url}/questionnaire/answers", json={
        "answers": {}
    })
    assert r.status_code == 400, f"Expected 400 for empty answers, got {r.status_code}"
    assert "answers" in r.text.lower() or "empty" in r.text.lower()


def test_questionnaire_submit_missing_answers(user_token_and_session, base_url):
    """
    Verify POST /questionnaire/answers rejects missing answers field.
    
    Request body: {}
    Expected: 400 with error message
    """
    access, http = user_token_and_session

    r = http.post(f"{base_url}/questionnaire/answers", json={})
    assert r.status_code == 400, f"Expected 400 for missing answers, got {r.status_code}"


def test_questionnaire_submit_invalid_question_id(user_token_and_session, base_url):
    """
    Verify POST /questionnaire/answers rejects invalid question IDs.
    
    Request body: { "answers": { "invalid-uuid": "1" } }
    Expected: 400 with error message
    """
    access, http = user_token_and_session
    
    fake_question_id = str(uuid.uuid4())
    
    r = http.post(f"{base_url}/questionnaire/answers", json={
        "answers": {
            fake_question_id: "1"
        }
    })
    # Should fail because question doesn't exist
    assert r.status_code == 400, f"Expected 400 for invalid question ID, got {r.status_code}"


def test_questionnaire_submit_answers_unauthorized(base_url):
    """
    Verify POST /questionnaire/answers requires authentication.
    
    Expected: 401 Unauthorized
    """
    import requests
    http = requests.Session()
    
    r = http.post(f"{base_url}/questionnaire/answers", json={
        "answers": {"some-id": "1"}
    })
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ==========================================
# Full Flow (if questions exist)
# ==========================================


def test_questionnaire_full_flow(user_token_and_session, base_url):
    """
    Verify full questionnaire flow: get questions, submit answers.
    
    Note: This test may skip if no questions are defined in the system.
    """
    access, http = user_token_and_session

    # Get available questions
    r = http.get(f"{base_url}/questionnaire/questions")
    assert r.status_code == 200
    
    questions = r.json()
    if not questions:
        pytest.skip("No questions defined in the system - skipping full flow test")
    
    # Build answers dict: for each question, select first option (index "1")
    answers = {}
    for q in questions:
        question_id = q.get("id")
        options = q.get("options", [])
        if question_id and options:
            # Select position 1 (first option)
            answers[question_id] = "1"
    
    if not answers:
        pytest.skip("No valid questions with options found")
    
    # Submit answers
    r = http.post(f"{base_url}/questionnaire/answers", json={
        "answers": answers
    })
    assert r.status_code == 200, f"questionnaire/answers failed: {r.status_code} {r.text}"
    
    data = r.json()
    assert data.get("ok") is True


# ==========================================
# Question CRUD Tests (admin-level)
# ==========================================


def test_question_add(user_token_and_session, base_url):
    """Test question creation with options."""
    access, http = user_token_and_session

    question_payload = {
        "text": "Test question?",
        "type": "note",
        "active": True,
        "options": ["Yes", "No", "Maybe"],
    }

    r = http.post(f"{base_url}/question/add", json=question_payload)
    assert r.status_code == 201, f"question/add failed: {r.text}"
    qid = r.json()["id"]

    # Cleanup
    http.delete(f"{base_url}/question/delete/{qid}")


def test_question_list_all(user_token_and_session, base_url):
    """Test listing all questions."""
    access, http = user_token_and_session

    r = http.get(f"{base_url}/question/all")
    assert r.status_code == 200
    
    data = r.json()
    assert isinstance(data, list)


def test_question_update(user_token_and_session, base_url):
    """Test question update."""
    access, http = user_token_and_session

    # Create question
    r = http.post(f"{base_url}/question/add", json={
        "text": "Original question?",
        "type": "note",
        "active": True,
        "options": ["A", "B"],
    })
    assert r.status_code == 201
    qid = r.json()["id"]

    # Update
    r = http.patch(f"{base_url}/question/update/{qid}", json={
        "text": "Updated question?"
    })
    assert r.status_code == 200

    # Cleanup
    http.delete(f"{base_url}/question/delete/{qid}")


def test_question_delete(user_token_and_session, base_url):
    """Test question deletion."""
    access, http = user_token_and_session

    # Create question
    r = http.post(f"{base_url}/question/add", json={
        "text": "To be deleted?",
        "type": "note",
        "active": True,
        "options": ["Yes", "No"],
    })
    assert r.status_code == 201
    qid = r.json()["id"]

    # Delete
    r = http.delete(f"{base_url}/question/delete/{qid}")
    assert r.status_code == 204

    # Verify deleted
    r = http.get(f"{base_url}/question/all")
    assert r.status_code == 200
    assert qid not in [q["id"] for q in r.json()]


def test_question_add_missing_options(user_token_and_session, base_url):
    """Test question creation fails without options."""
    access, http = user_token_and_session

    r = http.post(f"{base_url}/question/add", json={
        "text": "Question without options?",
        "type": "note",
        "active": True,
        # Missing options
    })
    assert r.status_code == 400

