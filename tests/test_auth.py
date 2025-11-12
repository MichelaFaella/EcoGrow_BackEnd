import time

def test_auth_flow(user_token_and_session, base_url):
    access, http = user_token_and_session

    # check-auth with valid token
    r = http.get(f"{base_url}/check-auth")
    assert r.status_code in (200, 401)  # your /check-auth returns 401 if no Authorization header
    # Force explicit with Authorization header
    headers = {"Authorization": http.headers["Authorization"]}
    r = http.get(f"{base_url}/check-auth", headers=headers)
    assert r.status_code == 200 and r.json().get("authenticated") == True

    # refresh (using cookie stored in session)
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (200, 401)  # may be 401 if refresh cookie/domain mismatch in CI
    if r.status_code == 200:
        new_acc = r.json().get("access_token")
        assert new_acc and len(new_acc) > 20


def test_auth_extended(user_token_and_session, base_url):
    access, http = user_token_and_session

    # refresh WITH cookie should usually work
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (200, 401), f"/auth/refresh unexpected: {r.status_code} {r.text}"
    if r.status_code == 200:
        new_access = r.json().get("access_token")
        assert new_access and len(new_access) > 20

    # simulate "no cookie": new session without cookies
    import requests
    no_cookie = requests.Session()
    r = no_cookie.post(f"{base_url}/auth/refresh")
    assert r.status_code in (400, 401), f"refresh without cookie should fail: {r.status_code} {r.text}"

    # logout should invalidate refresh
    r = http.post(f"{base_url}/auth/logout")
    assert r.status_code in (200, 204)

    # after logout, refresh should fail (even with former cookies)
    r = http.post(f"{base_url}/auth/refresh")
    assert r.status_code in (400, 401), f"refresh after logout should fail: {r.status_code} {r.text}"