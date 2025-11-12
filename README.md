# 🌿 EcoGrow Backend

This directory contains the **backend implementation** of the *EcoGrow Application*, built in **Python (Flask)**.  
It provides RESTful APIs for the Flutter frontend, handles plant data, image analysis, disease recognition (AI model), and reminders.

---

## 🧩 Project Structure with Comments

```bash
backend/
├── app.py                         # Main entry point – initializes and runs the Flask app
├── requirements.txt               # Python dependencies list 
│
├── api/                            # API layer: defines endpoints and request routing
│   ├── __init__.py                 # Marks folder as a Python package
│   ├── routes.py                   # Contains REST API endpoints (e.g., /plants, /check-auth)
│   └── controllers.py              # (Optional) Complex logic for specific API routes
│
├── services/                       # Core logic of the backend (business layer)
│   ├── __init__.py
│   ├── repository_service.py       # Handles database CRUD operations for plants, users, etc.
│   ├── image_processing_service.py # Preprocesses images (resize, compression, format conversion)
│   ├── reminder_service.py         # Manages reminders and scheduling for plant care
│   └── disease_recognition_service.py # Connects to AI module for plant disease detection
│
├── models/                         # ORM models and database schema definitions
│   ├── __init__.py
│   ├── base.py                     # SQLAlchemy base setup (engine, session, Base)
│   └── entities.py                 # Contains ORM entity classes (User, Plant, Reminder)
│
├── utils/                          # Helper functions and configurations
│   ├── __init__.py
│   ├── config.py                   # Stores environment variables and app configurations
│   └── plantnet_client.py          # Wrapper for external PlantNet API (plant species detection)
│
├── AI/                             # Machine learning module for disease recognition
│   ├── __init__.py                 # Makes the folder importable as a module
│   │
│   ├── dataset/                    # Training dataset for the disease recognition model
│   │   ├── healthy/                # Folder containing images of healthy plants
│   │   └── diseased/               # Folder containing images of diseased plants
│   │
│   ├── model/                      # Model architecture and weights
│   │   ├── cnn_model.py            # Defines the CNN or deep learning model used for recognition
│   │   └── trained_model.pth       # Pre-trained model weights (PyTorch format)
│   │
│   ├── training.py                 # Script for training the model (reads dataset, saves weights)
│   └── inference.py                # Script for running inference/predictions on uploaded images
│
└── tests/                          # Unit and integration tests
    ├── test_api.py                 # Tests API endpoints using simulated HTTP requests
    └── test_services.py            # Tests internal logic of the service layer
```

---

## 📁 Folder and File Descriptions

### `app.py`
**Main entry point** of the Flask backend.  
- Initializes the Flask app  
- Registers Blueprints from the `api/` module  
- Configures the database connection  
- Starts the Flask server using `python app.py` (default **port 8000**)

---

### `api/` – API Layer
Handles all incoming HTTP requests from the Flutter frontend.

| File | Description |
|------|--------------|
| `routes.py` | Defines REST API endpoints such as `/check-auth`, `/plants`, `/upload-plant-photo`. Calls appropriate service functions. |
| `controllers.py` | Optional module for advanced route logic or complex request processing. |
| `__init__.py` | Initializes the package so it can be imported in `app.py`. |

---

### `services/` – Business Logic
Implements backend operations separated by responsibility.

| File | Description |
|------|--------------|
| `repository_service.py` | Manages database operations (get, insert, update, delete). |
| `image_processing_service.py` | Handles preprocessing of uploaded images before AI analysis. |
| `reminder_service.py` | Creates and manages user reminders (e.g., watering schedule). |
| `disease_recognition_service.py` | Loads the AI model from `/AI/` and runs inference on plant images. |

---

### `models/` – ORM Models
Defines database structure using SQLAlchemy.

| File | Description |
|------|--------------|
| `base.py` | Sets up SQLAlchemy engine and session factory. |
| `entities.py` | Defines ORM entity classes (`User`, `Plant`, `Reminder`, etc.). |

---

### `utils/` – Helpers and Config
Utility modules and configuration management.

| File | Description |
|------|--------------|
| `config.py` | Stores configuration values (e.g., DB credentials, API keys, environment settings). |
| `plantnet_client.py` | Wrapper for the external PlantNet API to identify plant species based on images. |

---

### `AI/` – Machine Learning Module
Handles **training and inference** of the disease recognition model.

| File / Folder | Description |
|----------------|--------------|
| `dataset/` | Contains images used for training (`healthy/`, `diseased/`). |
| `model/` | Contains model architecture (`cnn_model.py`) and pre-trained weights (`trained_model.pth`). |
| `training.py` | Script for training the CNN using the dataset and saving the weights. |
| `inference.py` | Loads the trained model and predicts plant disease from a given image. |
| `__init__.py` | Marks the folder as a Python module for import. |

---

### `tests/` – Testing Suite
Contains both **unit** and **integration tests**.

| File | Description |
|------|--------------|
| `test_api.py` | Tests all REST API endpoints using simulated HTTP calls. |
| `test_services.py` | Tests each service class logic individually. |

---

## 📦 Requirements

`requirements.txt` (minimal set – add others as needed):
```
Flask==3.0.0
SQLAlchemy==2.0.0
requests==2.31.0
Pillow==10.0.0
python-dotenv==1.0.1
PyMySQL>=1.1.0
torch==2.2.2
torchvision==0.17.2
numpy==1.26.4
PyJWT==2.9.0
gunicorn==21.2.0
cryptography>=42.0.0
mysql-replication>=1.0.7

```
Install:
```bash
pip install -r requirements.txt
```

---

## 🚀 Run the Backend

1. **Create and activate a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\Scripts\activate    # Windows
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Flask server**
   ```bash
   python app.py
   ```

Server runs at:  
`http://127.0.0.1:8000` (or `http://localhost:8000`)

---

## 🔐 Authentication (JWT) – Quickstart

> `POST /api/auth/login` returns `{ "access_token": "<JWT>" }`.  
> For **write** endpoints add header: `Authorization: Bearer <JWT>`.

### Create a user (server hashes `password` automatically)
```bash
BASE="http://localhost:8000/api"
TS=$(date +%s)
EMAIL="user+$TS@example.com"
PASS="MyPass123"

curl -s -X POST "$BASE/user/add" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"first_name\":\"User\",\"last_name\":\"Demo\"}" | jq
```
### Login → TOKEN
```bash
TOKEN=$(curl -s -X POST "$BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | jq -r .access_token)
echo "TOKEN=$TOKEN"
```

### Check
```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/check-auth" | jq
```

---

## 🔗 API Endpoints Overview (selected)

| Endpoint | Method | Description |
|-----------|--------|-------------|
| `/health` | GET | App health. |
| `/check-auth` | GET | Checks if the JWT is valid. |
| `/auth/login` | POST | Issues access token for valid credentials. |
| `/family/*`, `/plant/*` | CRUD for families and plants (writes require JWT). |

---

## 🩺 Health Check
```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

---

## 🔗 Endpoints – updated usage (EcoGrow API)

> Base URL for the examples:
>
> ```bash
> BASE="http://localhost:8000/api"
> ```
>
> All responses are JSON. IDs are UUIDs. **Protected** endpoints require `Authorization: Bearer <ACCESS_JWT>`.

---

### 🔐 Authentication (JWT + Refresh cookie)
**Create user**  
```bash
EMAIL="you@example.com"; PASS="Abc!2345"
curl -s -X POST "$BASE/user/add" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"first_name\":\"You\",\"last_name\":\"Dev\"}" | jq .
```

**Login → ACCESS_JWT (+ save HttpOnly cookie for refresh)**  
```bash
TOKEN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  -c cookies.txt | jq -r .access_token)
echo "${TOKEN:0:20}..."
```

**Check-auth (with Authorization header)**  
```bash
curl -s "$BASE/check-auth" -H "Authorization: Bearer $TOKEN" | jq .
# If headers/cookies are missing → 401 {"authenticated": false}
```

**Refresh ACCESS_JWT (requires `refresh_token` cookie)**  
```bash
NEW_TOKEN=$(curl -s -X POST "$BASE/auth/refresh" -b cookies.txt -c cookies.txt | jq -r .access_token)
echo "${NEW_TOKEN:0:20}..."
```

**Logout (invalidates refresh + removes cookie)**  
```bash
curl -s -X POST "$BASE/auth/logout" -b cookies.txt -c cookies.txt | jq .
```

> Note: **Refresh** is valid for `REFRESH_TTL_DAYS` (default **90 days**) and is **sliding**—it is renewed on each successful `/auth/refresh` call.

---

### 🌿 Family
**List (public)**  
```bash
curl -s "$BASE/family/all" | jq .
curl -s "$BASE/families"    | jq .   # public alias
```

**Create / Update / Delete (protected)**  
```bash
FAM_ID=$(curl -s -X POST "$BASE/family/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"example1"}' | jq -r .id)

curl -s -X PATCH "$BASE/family/update/$FAM_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"description":"Tropical family"}' | jq .

curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/family/delete/$FAM_ID" \
  -H "Authorization: Bearer $TOKEN"
```

> **Important (constraint for `Plant`)**: creating a **Plant** automatically derives `family_id` from the **scientific name** using the `utils/house_plants.json` mapping, but the **Family must already exist in the DB** with the **same name**. If the mapping cannot find the family → `400 {"error":"Family not found"}`.

---

### 🌱 Plant
**List (public)**  
```bash
curl -s "$BASE/plants/all" | jq .
curl -s "$BASE/plants"     | jq .   # public alias
```

**Filters (public)**  
```bash
curl -s "$BASE/plants/by-use/ornamental" | jq .
curl -s "$BASE/plants/by-size/medium"    | jq .   # invalid size → 400
```

**Create (protected)** — *requires the species to exist in the mapping and the same-named Family to be present in the DB*  
```bash
# 1) ensure the Family consistent with the mapping
ensure_family_id=$(curl -s -X POST "$BASE/family/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"example1"}' | jq -r .id)

# 2) create the Plant (family_id is derived on the backend from scientific_name)
curl -s -X POST "$BASE/plant/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "scientific_name":"Aeschynanthus lobianus",
        "common_name":"Lipstick plant",
        "use":"ornamental",
        "water_level":2,
        "light_level":5,
        "difficulty":3,
        "min_temp_c":12,
        "max_temp_c":30,
        "category":"hanging",
        "climate":"tropical",
        "size":"medium"
      }' | jq .
# If the species is not in the mapping or the Family does not exist in the DB → 400 "Family not found"
```

**Update / Delete (protected)**  
```bash
PLANT_ID="<UUID>"
curl -s -X PATCH "$BASE/plant/update/$PLANT_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"size":"small"}' | jq .

curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant/delete/$PLANT_ID" \
  -H "Authorization: Bearer $TOKEN"
```
> **Note**: on creation, if a user↔plant link does not exist, the backend automatically creates a **UserPlant** (with a default `nickname` if missing).

---

### 👤↔️🌱 UserPlant (ownership)
**List / Add / Delete (protected)**  
```bash
# list
curl -s "$BASE/user_plant/all" -H "Authorization: Bearer $TOKEN" | jq .

# link ownership
curl -s -X POST "$BASE/user_plant/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"plant_id\":\"$PLANT_ID\"}" | jq .

# unlink (querystring)
UID=$(curl -s "$BASE/check-auth" -H "Authorization: Bearer $TOKEN" | jq -r .user_id)
URL="$BASE/user_plant/delete?user_id=$UID&plant_id=$PLANT_ID"

curl -sS -i --fail-with-body -X DELETE "$URL" -H "Authorization: Bearer $TOKEN"
```

> **Ownership required** for: `watering_plan/*`, `watering_log/*`, `plant_disease/*`.

---

### 💧 WateringPlan (protected)
```bash
# Create (requires plant ownership)
curl -s -X POST "$BASE/user_plant/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"plant_id\":\"$PLANT_ID\"}" | jq .
#remember to create another plant if you already deleted it

curl -s -X POST "$BASE/watering_plan/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"plant_id\":\"$PLANT_ID\",\"next_due_at\":\"2030-01-01 08:00:00\",\"interval_days\":5}" | jq .

# List / Update / Delete
curl -s "$BASE/watering_plan/all" -H "Authorization: Bearer $TOKEN" | jq .

WP_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_plan/update/$WP_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"interval_days":7}' | jq .

curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_plan/delete/$WP_ID" \
  -H "Authorization: Bearer $TOKEN"
```

### 🪣 WateringLog (protected)
```bash
# Create (requires plant ownership)
curl -s -X POST "$BASE/watering_log/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"plant_id\":\"$PLANT_ID\",\"done_at\":\"2030-01-01 09:00:00\",\"amount_ml\":150}" | jq .

# List / Update / Delete
curl -s "$BASE/watering_log/all" -H "Authorization: Bearer $TOKEN" | jq .

LOG_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_log/update/$LOG_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"amount_ml":200}' | jq .

curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_log/delete/$LOG_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 🧫 Disease & PlantDisease (protected)
```bash
# Disease CRUD
DIS_ID=$(curl -s -X POST "$BASE/disease/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Rust","description":"fungal"}' | jq -r .id)

curl -s -X PATCH "$BASE/disease/update/$DIS_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"treatment":"sulfur"}' | jq .

# Link disease ↔ plant (requires plant ownership)
curl -s -X POST "$BASE/plant_disease/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"plant_id\":\"$PLANT_ID\",\"disease_id\":\"$DIS_ID\",\"severity\":2,\"notes\":\"leaf spots\"}" | jq .
```

---

### 👥 Friendship & 🔁 SharedPlant (protected)
**Friendship** (fields required by the backend: `user_id_a`, `user_id_b`, `status`)  
```bash
ME=$(curl -s "$BASE/check-auth" -H "Authorization: Bearer $TOKEN" | jq -r .user_id)
UID2=$(curl -s -X POST "$BASE/user/add" -H "Content-Type: application/json" \
  -d "{\"email\":\"friend_$(date +%s)@test.local\",\"password\":\"Abc2345\",\"first_name\":\"Friend\",\"last_name\":\"User\"}" | jq -r .id)

FID=$(curl -s -X POST "$BASE/friendship/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"user_id_a\":\"$ME\",\"user_id_b\":\"$UID2\",\"status\":\"pending\"}" | jq -r .id)

curl -s -X PATCH "$BASE/friendship/update/$FID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"accepted"}' | jq .
```

**SharedPlant** (prefer `owner_user_id` / `recipient_user_id`; fallback `user_id_a` / `user_id_b`)  
```bash
SP=$(curl -s -X POST "$BASE/shared_plant/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"owner_user_id\":\"$ME\",\"recipient_user_id\":\"$UID2\",\"plant_id\":\"$PLANT_ID\"}" | jq -r .id)

curl -s -X PATCH "$BASE/shared_plant/update/$SP" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"note":"handle with care"}' | jq .
```

---

### 📝 Question & ⏰ Reminder (protected)
```bash
QID=$(curl -s -X POST "$BASE/question/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Direct light?","type":"note"}' | jq -r .id)

curl -s -X PATCH "$BASE/question/update/$QID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Better indirect light"}' | jq .

RID=$(curl -s -X POST "$BASE/reminder/add" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Check pests","scheduled_at":"2030-01-02 09:00:00"}' | jq -r .id)

curl -s -X PATCH "$BASE/reminder/update/$RID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Check aphids"}' | jq .
```

---

### 📸 PlantPhoto & Upload (protected)
```bash
# via URL
PID="$PLANT_ID"
PHOTO_ID=$(curl -s -X POST "$BASE/plant/photo/add/$PID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/one.jpg","caption":"one","order_index":0}' | jq -r .id)

curl -s -X PATCH "$BASE/plant/photo/update/$PHOTO_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"caption":"main"}' | jq .

# binary upload (multipart)
curl -s -X POST "$BASE/upload/plant-photo" \
  -H "Authorization: Bearer $TOKEN" \
  -F "plant_id=$PID" -F "caption=bin-file" -F "file=@/path/to/local.jpg" | jq .

# list / main photo
curl -s "$BASE/plant/$PID/photos?limit=1" | jq .
curl -s "$BASE/plant/$PID/photo"          | jq .

# delete (DB + file under /uploads)
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant-photo/delete/$PHOTO_ID" \
  -H "Authorization: Bearer $TOKEN"
```

> Uploaded files are served from `GET /uploads/<path>` (at the app **root**). If you delete files manually from the filesystem, you may leave orphan DB records: always use the delete endpoint.

---

### 🩺 Health & Ping (public)
```bash
curl -s "http://localhost:8000/health" | jq .   # {"status":"ok"}
curl -s "$BASE/ping"                   | jq .   # {"ping":"pong"}
```

---

### 🧭 Common error codes
- **401**: missing/invalid JWT; refresh without cookie.
- **400**: validation failed (e.g., invalid size; `"Family not found"` when mapping doesn’t resolve).
- **403**: acting on resources without ownership (Watering*/PlantDisease).
- **404**: resource not found / invalid ID / missing upload path.
- **409/500**: uniqueness conflicts (duplicates).