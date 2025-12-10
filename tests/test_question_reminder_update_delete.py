def test_question_reminder_update_delete(user_token_and_session, base_url):
    access, http = user_token_and_session

    # ==========================
    # QUESTION
    # ==========================
    # /question/add ora richiede:
    # - text (stringa non vuota)
    # - type (stringa non vuota)
    # - options: lista NON vuota
    question_payload = {
        "text": "Nebulizzare?",
        "type": "note",
        "active": True,
        "options": [
            "Sì",
            "No",
            "Solo in estate",
        ],
    }

    r = http.post(f"{base_url}/question/add", json=question_payload)
    assert r.status_code == 201, r.text
    qid = r.json()["id"]

    # update solo del text (la route supporta text/type/active)
    r = http.patch(
        f"{base_url}/question/update/{qid}",
        json={"text": "Nebulizzare ogni 2gg?"},
    )
    assert r.status_code == 200

    # list all → la domanda deve esserci
    r = http.get(f"{base_url}/question/all")
    assert r.status_code == 200
    questions = r.json()
    assert any(x["id"] == qid for x in questions)

    # delete question
    r = http.delete(f"{base_url}/question/delete/{qid}")
    assert r.status_code == 204

    # ==========================
    # REMINDER
    # ==========================
    reminder_payload = {
        "title": "Rinvasa",
        "scheduled_at": "2030-03-01 08:00:00",
    }

    r = http.post(f"{base_url}/reminder/add", json=reminder_payload)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    # update titolo
    r = http.patch(
        f"{base_url}/reminder/update/{rid}",
        json={"title": "Rinvasa (primavera)"},
    )
    assert r.status_code == 200

    # list all → reminder presente
    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200
    reminders = r.json()
    assert any(x["id"] == rid for x in reminders)

    # delete reminder
    r = http.delete(f"{base_url}/reminder/delete/{rid}")
    assert r.status_code == 204
