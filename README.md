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

# Endpoints usage

Set base URL (and reuse `TOKEN` from the auth section):
```bash
BASE="http://localhost:8000/api"
```

All responses are JSON. IDs are UUIDs.

---

## 🌱 Plant

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/plant/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "scientific_name":"Lavandula angustifolia",
        "common_name":"Lavender",
        "use":"ornamental",
        "water_level":2,
        "light_level":5,
        "difficulty":5,
        "min_temp_c":-10,
        "max_temp_c":40,
        "category":"shrub",
        "climate":"mediterranean",
        "size":"medio"
      }' | jq .
```

**Update** (requires JWT)
```bash
PLANT_ID="<UUID>"
curl -s -X PATCH "$BASE/plant/update/$PLANT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "origin":"EU", "size":"grande" }' | jq .
```

**Delete** (requires JWT)
```bash
PLANT_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant/delete/$PLANT_ID" \
  -H "Authorization: Bearer $TOKEN"
# expected: 204
```

**Filters**
```bash
# by size: piccolo|medio|grande|gigante
curl -s "$BASE/plants/by-size/medio" | jq .

# by use (case-insensitive): e.g., ornamental, medicinal
curl -s "$BASE/plants/by-use/ornamental" | jq .
```

**List all**
```bash
curl -s "$BASE/plants/all" | jq .
```

---

## 🌿 Family

**List**
```bash
curl -s "$BASE/family/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/family/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Rosaceae", "description":"Rose family" }' | jq .
```

**Update** (requires JWT)
```bash
FAMILY_ID="<UUID>"
curl -s -X PATCH "$BASE/family/update/$FAMILY_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Rosaceae (updated)" }' | jq .
```

**Delete** (requires JWT)
```bash
FAMILY_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/family/delete/$FAMILY_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📸 PlantPhoto

> If you manage photos by **URL** (DB only), keep the `/plant/photo/*` routes below.  
> If you **upload files**, use the **Images API** section at the bottom.

**List (global)** (may require JWT)
```bash
curl -s "$BASE/plant_photo/all" | jq .
```

**Create by URL (requires JWT)**
```bash
PLANT_ID="<UUID>"
curl -s -X POST "$BASE/plant/photo/add/$PLANT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "url":"https://example.com/p1.jpg", "caption":"leaves", "order_index":0 }' | jq .
```

**Update (requires JWT)**
```bash
PHOTO_ID="<UUID>"
curl -s -X PATCH "$BASE/plant/photo/update/$PHOTO_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "caption":"leaves (macro)" }' | jq .
```

**Delete (requires JWT)**
```bash
PHOTO_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant/photo/delete/$PHOTO_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🧫 Disease

**List**
```bash
curl -s "$BASE/disease/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/disease/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Powdery mildew", "description":"Fungal disease", "treatment":"sulfur" }' | jq .
```

**Update** (requires JWT)
```bash
DIS_ID="<UUID>"
curl -s -X PATCH "$BASE/disease/update/$DIS_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "treatment":"combined treatment" }' | jq .
```

**Delete** (requires JWT)
```bash
DIS_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/disease/delete/$DIS_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🌱🔗 PlantDisease (Plant–Disease relation)

**List**
```bash
curl -s "$BASE/plant_disease/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/plant_disease/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "plant_id":"<PLANT_ID>", "disease_id":"<DIS_ID>", "severity":2 }' | jq .
```

**Update** (requires JWT)
```bash
PD_ID="<UUID>"
curl -s -X PATCH "$BASE/plant_disease/update/$PD_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "notes":"monitor", "severity":3 }' | jq .
```

**Delete** (requires JWT)
```bash
PD_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant_disease/delete/$PD_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 👤 User

**List** (may require JWT)
```bash
curl -s "$BASE/user/all" | jq .
```

**Create** (server hashes `password`)  
```bash
curl -s -X POST "$BASE/user/add" \
  -H "Content-Type: application/json" \
  -d '{
        "email":"alice@example.com",
        "password":"MyPass123",
        "first_name":"Alice",
        "last_name":"Green"
      }' | jq .
```

**Update** (requires JWT)
```bash
USER_ID="<UUID>"
curl -s -X PATCH "$BASE/user/update/$USER_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "first_name":"Alicia" }' | jq .
```

**Delete** (requires JWT)
```bash
USER_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/user/delete/$USER_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 👤🌱 UserPlant (ownership) — composite PK

**List** (may require JWT)
```bash
curl -s "$BASE/user_plant/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/user_plant/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "user_id":"<USER_ID>", "plant_id":"<PLANT_ID>", "nickname":"My Lavender" }' | jq .
```

**Delete** (requires JWT)
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  "$BASE/user_plant/delete?user_id=<USER_ID>&plant_id=<PLANT_ID>" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🤝 Friendship

**List** (may require JWT)
```bash
curl -s "$BASE/friendship/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/friendship/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "user_id_a":"<USER_A>", "user_id_b":"<USER_B>", "status":"pending" }' | jq .
```

**Update** (requires JWT)
```bash
FRIEND_ID="<UUID>"
curl -s -X PATCH "$BASE/friendship/update/$FRIEND_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "status":"accepted" }' | jq .
```

**Delete** (requires JWT)
```bash
FRIEND_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/friendship/delete/$FRIEND_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🔁 SharedPlant (sharing)

**List** (may require JWT)
```bash
curl -s "$BASE/shared_plant/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/shared_plant/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "owner_user_id":"<OWNER_ID>", "recipient_user_id":"<RECIP_ID>", "plant_id":"<PLANT_ID>", "can_edit":true }' | jq .
```

**Update** (requires JWT)
```bash
SP_ID="<UUID>"
curl -s -X PATCH "$BASE/shared_plant/update/$SP_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "can_edit":false }' | jq .
```

**Delete** (requires JWT)
```bash
SP_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/shared_plant/delete/$SP_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 💧 WateringPlan

**List** (may require JWT)
```bash
curl -s "$BASE/watering_plan/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/watering_plan/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "plant_id":"<PLANT_ID>",
        "next_due_at":"2025-12-01T08:00:00",
        "interval_days":7,
        "check_soil_moisture":true
      }' | jq .
```

**Update** (requires JWT)
```bash
WP_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_plan/update/$WP_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "interval_days":10 }' | jq .
```

**Delete** (requires JWT)
```bash
WP_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_plan/delete/$WP_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🧾 WateringLog

**List** (may require JWT)
```bash
curl -s "$BASE/watering_log/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/watering_log/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "plant_id":"<PLANT_ID>",
        "done_at":"2025-12-01T09:30:00",
        "amount_ml":500,
        "note":"plentiful watering"
      }' | jq .
```

**Update** (requires JWT)
```bash
WL_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_log/update/$WL_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "amount_ml":450 }' | jq .
```

**Delete** (requires JWT)
```bash
WL_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_log/delete/$WL_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## ❓ Question

**List** (may require JWT)
```bash
curl -s "$BASE/question/all" | jq .
```

**Create** (requires JWT)
```bash
curl -s -X POST "$BASE/question/add" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "text":"How many hours of light does the plant get?",
        "type":"text"
      }' | jq .
```

**Update** (requires JWT)
```bash
Q_ID="<UUID>"
curl -s -X PATCH "$BASE/question/update/$Q_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "user_answer":"~5 hours", "answered_at":"2025-12-02T10:00:00" }' | jq .
```

**Delete** (requires JWT)
```bash
Q_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/question/delete/$Q_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

# Images API — Examples  (file uploads)

> Base URL: `http://localhost:8000`  
> API prefix: `/api`

## Variables (file and plant_id are examples, put yours)
```bash
API="http://localhost:8000/api"
PLANT_ID="2bd7da1f-76d6-4bcb-8511-0716ce95bb43"
FILE="./uploads/shrek.png"
```

## Upload a plant photo (requires JWT)
```bash
RESP_UPLOAD=$(curl -s -X POST "$API/upload/plant-photo" \
  -H "Authorization: Bearer $TOKEN" \
  -F "plant_id=$PLANT_ID" \
  -F "file=@$FILE")

echo "$RESP_UPLOAD" | jq
PHOTO_ID=$(echo "$RESP_UPLOAD" | jq -r .photo_id)
URL=$(echo "$RESP_UPLOAD" | jq -r .url)
echo "PHOTO_ID=$PHOTO_ID"
echo "URL=$URL"
```

## Get main photo for a plant
```bash
curl -s "$API/plant/$PLANT_ID/photo" | jq
```

## List photos for a plant
```bash
curl -s "$API/plant/$PLANT_ID/photos?limit=10" | jq
```

## Fetch file headers for the returned URL
```bash
curl -I "http://localhost:8000$URL"
```

## Delete a plant photo by id (requires JWT)
```bash
curl -i -X DELETE "$API/plant-photo/delete/$PHOTO_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## Verify list after deletion
```bash
curl -s "$API/plant/$PLANT_ID/photos" | jq
```

## Bulk delete all photos for a plant (requires JWT)
```bash
curl -s "$API/plant/$PLANT_ID/photos" | jq -r '.[].id' \
| while read -r PID; do
  curl -s -X DELETE "$API/plant-photo/delete/$PID" \
    -H "Authorization: Bearer $TOKEN" > /dev/null
done

curl -s "$API/plant/$PLANT_ID/photos" | jq
```