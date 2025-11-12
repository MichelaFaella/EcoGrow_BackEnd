import requests

def test_protected_endpoints_require_auth(base_url):
    http = requests.Session()
    http.headers.update({"Content-Type":"application/json"})

    # protected POSTs
    endpoints = [
        ("/plant/add", {"scientific_name":"X", "common_name":"X", "use":"ornamental", "water_level":2, "light_level":3, "difficulty":3, "min_temp_c":1, "max_temp_c":2, "category":"x", "climate":"x", "size":"small"}),
        ("/user_plant/add", {"plant_id":"00000000-0000-0000-0000-000000000000"}),
        ("/watering_plan/add", {"plant_id":"00000000-0000-0000-0000-000000000000","next_due_at":"2030-01-01T00:00:00Z","interval_days":7}),
        ("/watering_log/add", {"plant_id":"00000000-0000-0000-0000-000000000000","done_at":"2030-01-01T00:05:00Z","amount_ml":100}),
        ("/question/add", {"text":"x", "type":"note"}),
        ("/reminder/add", {"title":"x","scheduled_at":"2030-01-01T09:00:00Z"}),
        ("/family/add", {"name":"Zzz"}),
    ]
    for path, body in endpoints:
        r = http.post(f"{base_url}{path}", json=body)
        assert r.status_code in (401, 403), f"{path} should require auth, got {r.status_code} {r.text}"