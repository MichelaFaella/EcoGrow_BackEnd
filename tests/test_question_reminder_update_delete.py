def test_question_reminder_update_delete(user_token_and_session, base_url):
    access, http = user_token_and_session

    # Question
    r = http.post(f"{base_url}/question/add", json={"text": "Nebulizzare?", "type": "note"})
    assert r.status_code == 201
    qid = r.json()["id"]

    r = http.patch(f"{base_url}/question/update/{qid}", json={"text": "Nebulizzare ogni 2gg?"})
    assert r.status_code == 200

    r = http.get(f"{base_url}/question/all")
    assert r.status_code == 200 and any(x["id"] == qid for x in r.json())

    r = http.delete(f"{base_url}/question/delete/{qid}")
    assert r.status_code == 204

    # Reminder
    r = http.post(f"{base_url}/reminder/add", json={"title": "Rinvasa", "scheduled_at": "2030-03-01 08:00:00"})
    assert r.status_code == 201
    rid = r.json()["id"]

    r = http.patch(f"{base_url}/reminder/update/{rid}", json={"title": "Rinvasa (primavera)"})
    assert r.status_code == 200

    r = http.get(f"{base_url}/reminder/all")
    assert r.status_code == 200 and any(x["id"] == rid for x in r.json())

    r = http.delete(f"{base_url}/reminder/delete/{rid}")
    assert r.status_code == 204
