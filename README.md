# 🌿 EcoGrow Backend

This directory contains the **backend implementation** of the *EcoGrow Application*, built in **Python (Flask)**.  
It provides RESTful APIs for the Flutter frontend, handles plant data, image analysis, disease recognition (AI model), and reminders.

---

## 🧩 Project Structure with Comments

```bash
backend/
├── app.py                         # Main entry point – initializes and runs the Flask app
├── requirements.txt.txt                # Python dependencies list
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
- Starts the Flask server using `python app.py`

---

### `api/` – API Layer
Handles all incoming HTTP requests from the Flutter frontend.

| File | Description |
|------|--------------|
| `routes.py` | Defines REST API endpoints such as `/check-auth`, `/plants`, `/upload-image`. Calls appropriate service functions. |
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

Example:
```python
from AI.inference import predict_disease

class DiseaseRecognitionService:
    def analyze_image(self, image_path):
        return predict_disease(image_path)
```

---

### `models/` – ORM Models
Defines database structure using SQLAlchemy.

| File | Description |
|------|--------------|
| `base.py` | Sets up SQLAlchemy engine and session factory. |
| `entities.py` | Defines ORM entity classes (`User`, `Plant`, `Reminder`) with attributes and `to_dict()` methods. |

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

### `requirements.txt`
Defines all required Python packages.  
Example content:

```
Flask==3.0.0
SQLAlchemy==2.0.0
requests==2.31.0
Pillow==10.0.0
python-dotenv==1.0.1
PyMySQL==1.1.0
torch==2.2.2
torchvision==0.17.2
numpy==1.26.4
```

Install dependencies:
```bash
pip install -r requirements.txt.txt
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
   pip install -r requirements.txt.txt
   ```

3. **Run the Flask server**
   ```bash
   python app.py
   ```

Server runs at:  
`http://127.0.0.1:5000`

---

## 🔗 API Endpoints Overview

| Endpoint | Method | Description |
|-----------|--------|-------------|
| `/check-auth` | GET | Checks if the user is authenticated. |
| `/plants` | GET | Returns plants belonging to the authenticated user. |
| `/upload-image` | POST | Uploads and processes an image for analysis (calls AI inference). |

---

## 💡 Flutter Integration Example

Example request from Flutter:

```dart
final response = await http.get(
  Uri.parse('$baseUrl/plants'),
  headers: {'Authorization': 'Bearer <token>'},
);
```

---

## 🧠 Summary

| Folder | Purpose |
|---------|----------|
| `api/` | Handles HTTP routes and request flow |
| `services/` | Implements backend business logic |
| `models/` | Defines ORM models and DB mappings |
| `utils/` | Stores configurations and helpers |
| `AI/` | Contains ML model, training, and inference scripts |
| `tests/` | Contains all backend tests |

---


### 🐋Start / Stop (Docker)
```bash
# Build and start (detached)
docker compose up -d

# Follow logs
docker logs -f ecogrow-api
docker logs -f ecogrow-mysql

# Stop (DB data persists in the db_data volume)
docker compose down

# Stop and DELETE DB data (factory reset)
docker compose down -v
```

### 🩺 Health Check
```bash
curl -s http://localhost:8000/api/ping
# {"ping":"pong"}
```

### ⚙️ API Cheatsheet

**Families**
```bash
# Get all families (with plant counts)
curl -s http://localhost:8000/api/families
```

**Plants**
```bash
# Get ALL plants
curl -s http://localhost:8000/api/plants/all | jq
```

### ⛁ Inspect the Database
```bash
docker exec -it ecogrow-mysql bash
mysql -u root -p
passowrd to enter -> ecogrow

# Inside MySQL
SHOW DATABASES;
USE ecogrow;
SHOW TABLES;
DESCRIBE plant;
```

# Endpoints usage

Set a base URL for brevity:
```bash
BASE="http://localhost:8000/api"
```

All responses are JSON. IDs are UUIDs.

---

## 🌱 Plant

**Create**
```bash
curl -s -X POST "$BASE/plant/add" \
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
        "size":"medium"
      }' | jq .
```

**Update**
```bash
PLANT_ID="<UUID>"
curl -s -X PATCH "$BASE/plant/update/$PLANT_ID" \
  -H "Content-Type: application/json" \
  -d '{ "origin":"EU", "size":"large" }' | jq .
```

**Delete**
```bash
PLANT_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant/delete/$PLANT_ID"
# expected: 204
```

**Filters**
```bash
# by size: small|medium|large|giant
curl -s "$BASE/plants/by-size/medium" | jq .

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

**Create**
```bash
curl -s -X POST "$BASE/family/add" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Rosaceae" }' | jq .
```

**Update**
```bash
FAMILY_ID="<UUID>"
curl -s -X PATCH "$BASE/family/update/$FAMILY_ID" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Rosaceae (updated)" }' | jq .
```

**Delete**
```bash
FAMILY_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/family/delete/$FAMILY_ID"
```

---

## 📸 PlantPhoto

**List**
```bash
curl -s "$BASE/plant_photo/all" | jq .
```

**Create (for a plant)**
```bash
PLANT_ID="<UUID>"
curl -s -X POST "$BASE/plant/photo/add/$PLANT_ID" \
  -H "Content-Type: application/json" \
  -d '{ "url":"https://example.com/p1.jpg", "caption":"leaves", "order_index":0 }' | jq .
```

**Update**
```bash
PHOTO_ID="<UUID>"
curl -s -X PATCH "$BASE/plant/photo/update/$PHOTO_ID" \
  -H "Content-Type: application/json" \
  -d '{ "caption":"leaves (macro)" }' | jq .
```

**Delete**
```bash
PHOTO_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant/photo/delete/$PHOTO_ID"
```

---

## 🧫 Disease

**List**
```bash
curl -s "$BASE/disease/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/disease/add" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Powdery mildew", "description":"Fungal disease", "treatment":"sulfur" }' | jq .
```

**Update**
```bash
DIS_ID="<UUID>"
curl -s -X PATCH "$BASE/disease/update/$DIS_ID" \
  -H "Content-Type: application/json" \
  -d '{ "treatment":"combined treatment" }' | jq .
```

**Delete**
```bash
DIS_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/disease/delete/$DIS_ID"
```

---

## 🌱🔗 PlantDisease (Plant–Disease relation)

**List**
```bash
curl -s "$BASE/plant_disease/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/plant_disease/add" \
  -H "Content-Type: application/json" \
  -d '{ "plant_id":"<PLANT_ID>", "disease_id":"<DIS_ID>", "severity":2 }' | jq .
```

**Update**
```bash
PD_ID="<UUID>"
curl -s -X PATCH "$BASE/plant_disease/update/$PD_ID" \
  -H "Content-Type: application/json" \
  -d '{ "notes":"monitor", "severity":3 }' | jq .
```

**Delete**
```bash
PD_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/plant_disease/delete/$PD_ID"
```

---

## 👤 User

**List**
```bash
curl -s "$BASE/user/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/user/add" \
  -H "Content-Type: application/json" \
  -d '{
        "email":"alice@example.com",
        "password_hash":"<hashed>",
        "first_name":"Alice",
        "last_name":"Green"
      }' | jq .
```

**Update**
```bash
USER_ID="<UUID>"
curl -s -X PATCH "$BASE/user/update/$USER_ID" \
  -H "Content-Type: application/json" \
  -d '{ "first_name":"Alicia" }' | jq .
```

**Delete**
```bash
USER_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/user/delete/$USER_ID"
```

---

## 👤🌱 UserPlant (ownership) — composite PK

**List**
```bash
curl -s "$BASE/user_plant/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/user_plant/add" \
  -H "Content-Type: application/json" \
  -d '{ "user_id":"<USER_ID>", "plant_id":"<PLANT_ID>", "nickname":"My Lavender" }' | jq .
```

**Delete**
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  "$BASE/user_plant/delete?user_id=<USER_ID>&plant_id=<PLANT_ID>"
```

---

## 🤝 Friendship

**List**
```bash
curl -s "$BASE/friendship/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/friendship/add" \
  -H "Content-Type: application/json" \
  -d '{ "user_id_a":"<USER_A>", "user_id_b":"<USER_B>", "status":"pending" }' | jq .
```

**Update**
```bash
FRIEND_ID="<UUID>"
curl -s -X PATCH "$BASE/friendship/update/$FRIEND_ID" \
  -H "Content-Type: application/json" \
  -d '{ "status":"accepted" }' | jq .
```

**Delete**
```bash
FRIEND_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/friendship/delete/$FRIEND_ID"
```

---

## 🔁 SharedPlant (sharing)

**List**
```bash
curl -s "$BASE/shared_plant/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/shared_plant/add" \
  -H "Content-Type: application/json" \
  -d '{ "owner_user_id":"<OWNER_ID>", "recipient_user_id":"<RECIP_ID>", "plant_id":"<PLANT_ID>", "can_edit":true }' | jq .
```

**Update**
```bash
SP_ID="<UUID>"
curl -s -X PATCH "$BASE/shared_plant/update/$SP_ID" \
  -H "Content-Type: application/json" \
  -d '{ "can_edit":false }' | jq .
```

**Delete**
```bash
SP_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/shared_plant/delete/$SP_ID"
```

---

## 💧 WateringPlan

**List**
```bash
curl -s "$BASE/watering_plan/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/watering_plan/add" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "plant_id":"<PLANT_ID>",
        "next_due_at":"2025-12-01T08:00:00",
        "interval_days":7,
        "check_soil_moisture":true
      }' | jq .
```

**Update**
```bash
WP_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_plan/update/$WP_ID" \
  -H "Content-Type: application/json" \
  -d '{ "interval_days":10 }' | jq .
```

**Delete**
```bash
WP_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_plan/delete/$WP_ID"
```

---

## 🧾 WateringLog

**List**
```bash
curl -s "$BASE/watering_log/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/watering_log/add" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "plant_id":"<PLANT_ID>",
        "done_at":"2025-12-01T09:30:00",
        "amount_ml":500,
        "note":"plentiful watering"
      }' | jq .
```

**Update**
```bash
WL_ID="<UUID>"
curl -s -X PATCH "$BASE/watering_log/update/$WL_ID" \
  -H "Content-Type: application/json" \
  -d '{ "amount_ml":450 }' | jq .
```

**Delete**
```bash
WL_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/watering_log/delete/$WL_ID"
```

---

## ❓ Question

**List**
```bash
curl -s "$BASE/question/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/question/add" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "text":"How many hours of light does the plant get?",
        "type":"text"
      }' | jq .
```

**Update**
```bash
Q_ID="<UUID>"
curl -s -X PATCH "$BASE/question/update/$Q_ID" \
  -H "Content-Type: application/json" \
  -d '{ "user_answer":"~5 hours", "answered_at":"2025-12-02T10:00:00" }' | jq .
```

**Delete**
```bash
Q_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/question/delete/$Q_ID"
```

---

## ⏰ Reminder

**List**
```bash
curl -s "$BASE/reminder/all" | jq .
```

**Create**
```bash
curl -s -X POST "$BASE/reminder/add" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id":"<USER_ID>",
        "title":"Check Ficus soil",
        "scheduled_at":"2025-12-01T18:00:00"
      }' | jq .
```

**Update**
```bash
R_ID="<UUID>"
curl -s -X PATCH "$BASE/reminder/update/$R_ID" \
  -H "Content-Type: application/json" \
  -d '{ "note":"use moisture meter" }' | jq .
```

**Delete**
```bash
R_ID="<UUID>"
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "$BASE/reminder/delete/$R_ID"
```

---

# Images API — Examples  

> Base URL: `http://localhost:8000`  
> API prefix: `/api`


## Variables (file and plant_id are examples, put yours)

```bash
API="http://localhost:8000/api"
PLANT_ID="2bd7da1f-76d6-4bcb-8511-0716ce95bb43"
FILE="./uploads/shrek.png"
```


## Upload a plant photo

```bash
RESP_UPLOAD=$(curl -s -X POST "$API/upload/plant-photo" \
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



## Delete a plant photo by id

```bash
curl -i -X DELETE "$API/plant-photo/delete/$PHOTO_ID"
```



## Verify list after deletion

```bash
curl -s "$API/plant/$PLANT_ID/photos" | jq
```



## Bulk delete all photos for a plant

```bash
curl -s "$API/plant/$PLANT_ID/photos" | jq -r '.[].id' \
| while read -r PID; do
  curl -s -X DELETE "$API/plant-photo/delete/$PID" > /dev/null
done

curl -s "$API/plant/$PLANT_ID/photos" | jq
```