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

### Health Check
```bash
curl -s http://localhost:8000/api/ping
# {"ping":"pong"}
```

### API Cheatsheet

**Families**
```bash
# Get all families (with plant counts)
curl -s http://localhost:8000/api/families
```

**Plants**
```bash
# Get ALL plants
curl -s http://localhost:8000/api/plants/all | jq


### Inspect the Database
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