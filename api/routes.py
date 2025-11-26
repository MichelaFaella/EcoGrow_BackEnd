from __future__ import annotations

import base64
import io
import json
# Standard library
import os
import uuid
from contextlib import contextmanager
from datetime import datetime

import requests
from PIL import Image
# Third-party
from flask import Blueprint, jsonify, current_app, request, abort, g, url_for
from flask import current_app
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename, send_from_directory
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, DataError
from functools import wraps
from datetime import datetime, timedelta
import secrets

# Export/seed utilities
from models.scripts.replay_changes import seed_from_changes, write_changes_delete, write_changes_upsert
from models.base import SessionLocal
from services.image_processing_service import ImageProcessingService
from services.reminder_service import ReminderService

# Local application
from services.repository_service import RepositoryService
from utils.jwt_helper import generate_token, validate_token
from models.entities import SizeEnum, QuestionOption
from models.entities import (
    Disease,
    Family,
    Friendship,
    Plant,
    PlantDisease,
    PlantPhoto,
    Question,
    Reminder,
    SharedPlant,
    User,
    UserPlant,
    WateringLog,
    WateringPlan,
    RefreshToken,
)

api_blueprint = Blueprint("api", __name__)
repo = RepositoryService()
REFRESH_TTL_DAYS = int(os.getenv("REFRESH_TTL_DAYS", "90"))
DISEASE_PROB_THRESHOLD = float(os.getenv("DISEASE_PROB_THRESHOLD", "0.05"))
UPLOAD_FOLDER = "uploads"
MODEL_PREDICT_URL = os.getenv("MODEL_URL", "http://model:8000/predict")
MODEL_TIMEOUT = float(os.getenv("MODEL_TIMEOUT", "30"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANT_DISEASE_DETAILS_PATH = os.path.join(BASE_DIR, "plant_disease_details.json")
try:
    with open(PLANT_DISEASE_DETAILS_PATH, "r", encoding="utf-8") as f:
        PLANT_DISEASE_DETAILS = json.load(f)
except FileNotFoundError:
    PLANT_DISEASE_DETAILS = {}

image_service = ImageProcessingService()
reminder_service = ReminderService()


@api_blueprint.errorhandler(401)
def auth_missing(e):
    return jsonify({"error": "Missing or invalid JWT token"}), 401


# ======== AUTH =========
@api_blueprint.route("/auth/login", methods=["POST"])
def auth_login():
    """
    JSON body: { "email": "...", "password": "..." }

    Returns (200):
    {
      "access_token": "...",
      "user_id": "...",
      "first_name": "...",
      "last_name": "...",
      "user": {
        "id": "...",
        "email": "...",
        "first_name": "...",
        "last_name": "..."
      }
    }

    + HttpOnly cookie "refresh_token" per il refresh.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email/password missing"}), 400

    with _session_ctx() as s:
        # Cerca utente per email case-insensitive
        u: User | None = (
            s.query(User)
            .filter(func.lower(User.email) == email)
            .first()
        )

        if not u or not check_password_hash(u.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        # 1) Access JWT (short-lived)
        access_token = generate_token(str(u.id))

        # 2) Refresh token persistente in DB
        raw_refresh = secrets.token_urlsafe(48)
        rt = RefreshToken(
            user_id=str(u.id),
            token=raw_refresh,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TTL_DAYS),
        )
        s.add(rt)
        # se vuoi tracciare anche qui:
        # write_changes_insert("refresh_token", str(rt.id), {...})
        s.flush()  # opzionale, se ti serve l'id di rt
        # commit finale
        # (se hai un helper _commit_or_409 usalo qui)
        # _commit_or_409(s)

        # 3) Risposta JSON + cookie HttpOnly
        resp = jsonify({
            "access_token": access_token,
            "user_id": str(u.id),
            "first_name": u.first_name,
            "last_name": u.last_name,
            "user": {
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
            },
        })

        resp.set_cookie(
            "refresh_token",
            raw_refresh,
            max_age=60 * 60 * 24 * REFRESH_TTL_DAYS,
            httponly=True,
            secure=False,  # metti True in produzione con HTTPS
            samesite="Lax",
            path="/",
        )

        return resp, 200


@api_blueprint.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    # Il client NON manda nulla nel body: il refresh è nel cookie HttpOnly
    raw = request.cookies.get("refresh_token")
    if not raw:
        return jsonify({"error": "refresh token mancante"}), 401

    now = datetime.utcnow()
    with _session_ctx() as s:
        rt = s.query(RefreshToken).filter(RefreshToken.token == raw).first()
        if not rt or rt.expires_at < now:
            return jsonify({"error": "Refresh non valido o scaduto"}), 401

        # 1) Nuovo access JWT
        new_access = generate_token(rt.user_id)

        # 2) Sliding: rinnova scadenza refresh e aggiorna cookie
        rt.last_used_at = now
        rt.expires_at = now + timedelta(days=REFRESH_TTL_DAYS)
        _commit_or_409(s)

        resp = jsonify({"access_token": new_access, "user_id": rt.user_id})
        resp.set_cookie(
            "refresh_token",
            raw,  # in questo design non ruotiamo il valore, solo la scadenza
            max_age=60 * 60 * 24 * REFRESH_TTL_DAYS,
            httponly=True,
            secure=False,  # True in produzione (HTTPS)
            samesite="Lax",
            path="/",
        )
        return resp, 200


@api_blueprint.route("/auth/logout", methods=["POST"])
def auth_logout():
    raw = request.cookies.get("refresh_token")
    with _session_ctx() as s:
        if raw:
            s.query(RefreshToken).filter(RefreshToken.token == raw).delete()
            _commit_or_409(s)
    resp = jsonify({"ok": True})
    resp.delete_cookie("refresh_token", path="/")
    return resp, 200


def _extract_token() -> str | None:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth:
        return None
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return auth


def require_jwt(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        tok = _extract_token()
        user_id = validate_token(tok) if tok else None
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        g.user_id = user_id
        return fn(*args, **kwargs)

    return wrapper


# ========= Helpers =========
def _model_columns(Model) -> set[str]:
    """Returns the SQLAlchemy column names of the Model."""
    return {c.name for c in Model.__table__.columns}


def _filter_fields_for_model(payload: dict, Model, *, exclude: set[str] = None) -> dict:
    """Filters the payload keeping only fields that exist on the Model."""
    cols = _model_columns(Model)
    if exclude:
        cols = cols - set(exclude)
    return {k: v for k, v in payload.items() if k in cols}


def _serialize_full_plant(plant):
    # famiglia
    family_name = plant.family.name if plant.family else None
    family_description = (
        plant.family.description if plant.family else None
    )

    # foto compressa base64 (prendo la prima)
    photo_base64 = None
    if plant.photos:
        photo = plant.photos[0]  # la prima foto
        image_path = getattr(photo, "path", None)

        if image_path and os.path.exists(image_path):
            img = Image.open(image_path)
            img.thumbnail((800, 800), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60, optimize=True)
            buf.seek(0)
            photo_base64 = base64.b64encode(buf.read()).decode("utf-8")

    return {
        "id": str(plant.id),
        "scientific_name": plant.scientific_name,
        "common_name": plant.common_name,
        "category": plant.category,
        "climate": plant.climate,
        "origin": plant.origin,
        "use": plant.use,
        "size": plant.size,
        "water_level": plant.water_level,
        "light_level": plant.light_level,
        "min_temp_c": plant.min_temp_c,
        "max_temp_c": plant.max_temp_c,

        "family_name": family_name,
        "family_description": family_description,

        "photo_base64": photo_base64,
    }


def _serialize_with_relations(instance):
    print("\n===== DEBUG _serialize_with_relations START =====")

    # Serializziamo UserPlant
    data = _serialize_instance(instance)
    print("[LOG] DATA (dopo _serialize_instance):", data)

    plant = getattr(instance, "plant", None)
    if not plant:
        print("[LOG] Nessuna plant associata! RETURN")
        print("===== DEBUG _serialize_with_relations END =====\n")
        return data

    print("[LOG] Plant trovata, ID:", plant.id)
    print("[LOG] SIZE RAW:", plant.size, type(plant.size))

    # SERIALIZZAZIONE MANUALE DELLA PIANTA
    plant_data = {
        "id": str(plant.id),
        "scientific_name": plant.scientific_name,
        "common_name": plant.common_name,
        "category": plant.category,
        "climate": plant.climate,
        "origin": plant.origin,
        "use": plant.use,
        "difficulty": plant.difficulty,
        "light_level": plant.light_level,
        "min_temp_c": plant.min_temp_c,
        "max_temp_c": plant.max_temp_c,
        "family_id": str(plant.family_id) if plant.family_id else None,
        "created_at": plant.created_at.isoformat() if plant.created_at else None,
    }

    print("[LOG] plant_data PRIMA DI SIZE:", plant_data)

    # ENUM → STRING
    if plant.size is not None:
        size_value = plant.size.value
    else:
        size_value = None

    plant_data["size"] = size_value
    data["size"] = size_value

    print("[LOG] plant_data DOPO SIZE:", plant_data)
    print("[LOG] data DOPO SIZE:", data)

    # --- FOTO ---
    photos = getattr(plant, "photos", [])
    serialized_photos = []

    print("[LOG] Numero foto:", len(photos))

    for photo in photos:
        photo_data = _serialize_instance(photo)
        print("[LOG] Foto base:", photo_data)

        plant_id = str(plant.id)
        filename = photo.url

        if not filename:
            print("[LOG] Foto senza filename → aggiunta senza immagine")
            serialized_photos.append(photo_data)
            continue

        resized_filename = _get_or_create_resized_image(plant_id, filename)
        filename_only = os.path.basename(resized_filename or filename)
        image_path = os.path.join(UPLOAD_FOLDER, plant_id, filename_only)

        print("[LOG] Tentativo lettura immagine:", image_path)

        image_b64 = None
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=70, method=6)
                webp_bytes = buf.getvalue()

            image_b64 = base64.b64encode(webp_bytes).decode("ascii")
        except Exception as e:
            print(f"[WARN] Image compress failed for {filename}: {e}")

        photo_data["image"] = image_b64
        serialized_photos.append(photo_data)

    plant_data["photos"] = serialized_photos

    print("[LOG] plant_data FINALE:", plant_data)

    data["plant"] = plant_data

    print("[LOG] data FINALE PRIMA DEL RETURN:", data)
    print("===== DEBUG _serialize_with_relations END =====\n")

    return data


MAX_SIZE = (800, 800)  # risoluzione massima lato lungo


def _get_or_create_resized_image(plant_id: str, filename: str) -> str | None:
    """
    Ritorna il NOME FILE della versione compressa.
    Se non esiste, la crea a partire dall'originale.
    """
    # Caso: nel DB hai già un path tipo "uploads/..." → prendo solo il nome file
    filename_only = os.path.basename(filename)

    base, ext = os.path.splitext(filename_only)
    if not ext:
        ext = ".jpg"

    resized_name = f"{base}_small{ext}"
    orig_path = os.path.join(UPLOAD_FOLDER, plant_id, filename_only)
    resized_path = os.path.join(UPLOAD_FOLDER, plant_id, resized_name)

    # Se esiste già, riusala
    if os.path.exists(resized_path):
        return resized_name

    # Se non esiste neanche l'originale, non posso fare nulla
    if not os.path.exists(orig_path):
        print(f"[WARN] Original image not found: {orig_path}")
        return None

    try:
        with Image.open(orig_path) as img:
            img = img.convert("RGB")
            img.thumbnail(MAX_SIZE)
            os.makedirs(os.path.dirname(resized_path), exist_ok=True)
            img.save(resized_path, format="JPEG", quality=80, optimize=True)
            print(f"[DEBUG] Created resized image: {resized_path}")
            return resized_name
    except Exception as e:
        print(f"[ERROR] Failed to resize image {orig_path}: {e}")
        return None


def _serialize_instance(instance) -> dict:
    """
    Serializes the instance based on actual model columns:
    - converts UUID/DateTime to strings if needed
    - includes only actual columns (no extra attributes)
    """
    cols = _model_columns(type(instance))
    out = {}
    for c in cols:
        v = getattr(instance, c, None)
        # UUID → string (if needed)
        if v is not None and hasattr(v, "hex"):
            v = str(v)
        # datetime → ISO8601
        if isinstance(v, datetime):
            v = v.isoformat()
        out[c] = v
    return out


@contextmanager
def _session_ctx():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _ensure_uuid(s: str, field: str = "id"):
    try:
        uuid.UUID(str(s))
    except Exception:
        abort(400, description=f"Invalid {field} format")


def _parse_json_body():
    """
    JSON parser robusto che NON va mai in blocco.
    - Usa request.get_data() invece di request.json
    - Non fa buffering lento
    - Funziona dietro localtunnel / ngrok
    - Supporta payload grandi (base64)
    """

    try:
        raw = request.get_data(cache=False, as_text=True)
        print(f"[_parse_json_body] RAW length: {len(raw)}")

        if not raw:
            raise ValueError("Empty body")

        body = json.loads(raw)
        print(f"[_parse_json_body] JSON Parsed OK → keys: {list(body.keys())}")
        return body

    except Exception as e:
        print("[_parse_json_body] ERRORE PARSING:", e)
        raise


def _commit_or_409(session):
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        abort(409, description=f"Conflict: {e.orig}")
    except DataError as e:
        session.rollback()
        abort(400, description=f"Bad data: {e.orig}")
    except Exception as e:
        session.rollback()
        abort(500, description="Commit failed")


def _parse_unknown_threshold(raw_value) -> float | None:
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        raise ValueError("unknown_threshold must be a float between 0 and 1.") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError("unknown_threshold must be between 0.0 and 1.0.")
    return value


def _call_model_service(
        image_file,
        *,
        unknown_threshold: float | None = None,
        family: str | None = None,
        disease_suggestions: list[str] | None = None,
) -> dict:
    """Call the external model API or fall back to the inline service."""
    inline = not MODEL_PREDICT_URL or MODEL_PREDICT_URL.lower() in {"inline", "local", "self"}

    stream = getattr(image_file, "stream", image_file)
    if hasattr(stream, "seek"):
        stream.seek(0)
    filename = getattr(image_file, "filename", None) or "upload.jpg"
    mime = getattr(image_file, "mimetype", None) or getattr(image_file, "content_type",
                                                            None) or "application/octet-stream"

    if inline:
        from ecogrow_disease_detection.model_inference_service import get_disease_inference_service

        data = stream.read()
        service = get_disease_inference_service()
        result = service.predict_from_bytes(
            data,
            family=family,
            disease_suggestions=disease_suggestions,
            unknown_threshold=unknown_threshold,
        )
        return {"status": "success", "data": result}

    files = {"image": (filename, stream, mime)}
    data = []
    if unknown_threshold is not None:
        data.append(("unknown_threshold", str(unknown_threshold)))
    if family:
        data.append(("family", family))
    if disease_suggestions:
        for d in disease_suggestions:
            data.append(("disease_suggestions", d))

    try:
        resp = requests.post(
            MODEL_PREDICT_URL,
            files=files,
            data=data or None,
            timeout=MODEL_TIMEOUT,
        )
    except requests.Timeout as exc:  # noqa: BLE001
        raise RuntimeError("Model service timeout") from exc
    except requests.RequestException as exc:  # noqa: BLE001
        raise RuntimeError(f"Model service unreachable: {exc}") from exc

    if resp.status_code >= 400:
        # Try to surface error payload from model service
        try:
            payload = resp.json()
        except Exception:
            payload = None
        message = ""
        if isinstance(payload, dict):
            message = payload.get("error") or payload.get("message") or str(payload)
        elif payload:
            message = str(payload)
        raise RuntimeError(f"Model service error ({resp.status_code}): {message or resp.text}")

    try:
        payload = resp.json()
    except ValueError as exc:  # noqa: BLE001
        raise RuntimeError("Invalid JSON from model service") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected response format from model service")
    return payload


def _plant_to_dict(p: Plant) -> dict:
    """Serialize only the persistent fields you want in changes.json."""
    return {
        "id": str(p.id),
        "scientific_name": p.scientific_name,
        "common_name": getattr(p, "common_name", None),
        "use": getattr(p, "use", None),
        "origin": getattr(p, "origin", None),
        "water_level": getattr(p, "water_level", None),
        "light_level": getattr(p, "light_level", None),
        "min_temp_c": getattr(p, "min_temp_c", None),
        "max_temp_c": getattr(p, "max_temp_c", None),
        "author_id": getattr(p, "author_id", None),
        "created_at": getattr(p, "created_at", None),
        "updated_at": getattr(p, "updated_at", None),
        "family_id": getattr(p, "family_id", None),
    }


# ========= Auth check =========
@api_blueprint.route("/check-auth", methods=["GET"])
def check_auth():
    tok = _extract_token()
    user_id = validate_token(tok) if tok else None
    if not user_id:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user_id": user_id}), 200


@api_blueprint.route("/user/me", methods=["GET"])
@require_jwt
def user_me():
    print("\n---- [GET /user/me] START ----")

    user_id = g.user_id
    print(f"[GET /user/me] Extracted user_id from JWT: {user_id}")

    repo = RepositoryService()

    try:
        with repo.Session() as s:
            print("[GET /user/me] DB session opened")

            user = s.query(User).filter(User.id == user_id).first()

            if not user:
                print(f"[GET /user/me] User NOT FOUND in DB → id={user_id}")
                print("---- [GET /user/me] END (404) ----\n")
                return jsonify({"error": "User not found"}), 404

            print(f"[GET /user/me] User found in DB: {user.id} {user.first_name} {user.last_name}")

            serialized = _serialize_instance(user)
            print("[GET /user/me] Serialized user:", serialized)

            print("---- [GET /user/me] END (200) ----\n")
            return jsonify(serialized), 200

    except Exception as e:
        print(f"[GET /user/me] ERROR: {e}")
        print("---- [GET /user/me] END (500) ----\n")
        return jsonify({"error": "Internal server error"}), 500


# ========= Ping =========
@api_blueprint.route("/ping", methods=["GET"])
def ping():
    return jsonify(ping="pong")


@api_blueprint.route("/ai/model/disease-detection", methods=["POST"])
def ai_model_disease_detection():
    if "image" not in request.files:
        return jsonify({"error": "Missing 'image' file in request."}), 400

    body = request.get_json(silent=True) if request.is_json else None
    try:
        raw_thr = request.values.get("unknown_threshold")
        if raw_thr is None and isinstance(body, dict):
            raw_thr = body.get("unknown_threshold")
        unknown_threshold = _parse_unknown_threshold(raw_thr)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    family = request.values.get("family") or (body.get("family") if isinstance(body, dict) else None)
    disease_suggestions: list[str] = []
    if request.values:
        disease_suggestions.extend([v for v in request.values.getlist("disease_suggestions") if v])
    if isinstance(body, dict):
        raw = body.get("disease_suggestions")
        if isinstance(raw, list):
            disease_suggestions.extend([str(v) for v in raw if v is not None])

    try:
        # 👉 ora usi il service
        result = image_service.disease_detection_raw(
            image_file=request.files["image"],
            unknown_threshold=unknown_threshold,
            family=family,
            disease_suggestions=disease_suggestions or None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Inference failed: {exc}"}), 502

    return jsonify(result), 200


@api_blueprint.route("/families", methods=["GET"])
def get_families():
    try:
        families = repo.get_all_families()
        return jsonify(families), 200
    except Exception:
        return jsonify({"error": "Database error"}), 500


# ========= Plants (by user) =========
@api_blueprint.route("/uploads/<path:path>", methods=["GET"])
def serve_uploads(path):
    return send_from_directory(UPLOAD_FOLDER, path)


@api_blueprint.route("/plants", methods=["GET"])
@require_jwt
def get_plants():
    user_id = g.user_id

    try:
        plants = repo.get_plants_by_user(user_id)
        return jsonify(plants), 200
    except Exception as e:
        current_app.logger.exception(f"Error fetching plants for user {user_id}: {e}")
        return jsonify({"error": "Database error"}), 500


ALLOWED_SIZES = {e.value for e in SizeEnum}


# ========= Plants (catalog) =========
@api_blueprint.route("/plants/all", methods=["GET"])
def get_all_plants():
    try:
        plants = repo.get_all_plants_catalog()
        return jsonify(plants), 200
    except Exception:
        return jsonify({"error": "Database error"}), 500


@api_blueprint.route("/user/plants/sick", methods=["GET"])
@require_jwt
def get_user_sick_plants():
    """
    Restituisce tutte le piante dell'utente che hanno health_status='sick'
    (campo su UserPlant).

    Per ogni pianta ritorna anche l'ultima PlantDisease con status='confirmed',
    se presente.
    """
    user_id = g.user_id

    with _session_ctx() as s:
        # Join UserPlant -> Plant, e poi PlantDisease/Disease per le malattie
        q = (
            s.query(
                Plant,
                UserPlant.location_note,
                PlantDisease,
                Disease,
            )
            .join(UserPlant, UserPlant.plant_id == Plant.id)
            .outerjoin(PlantDisease, PlantDisease.plant_id == Plant.id)
            .outerjoin(Disease, Disease.id == PlantDisease.disease_id)
            .filter(
                UserPlant.user_id == user_id,
                UserPlant.health_status == "sick",
                PlantDisease.status == "confirmed",
            )
            # 👇 QUI: tolto .nulls_last(), che MySQL non supporta
            .order_by(PlantDisease.detected_at.desc())
        )

        rows = q.all()

        # Vogliamo una sola entry per pianta: prendiamo la malattia più recente
        by_plant: dict[str, dict] = {}
        for plant, location_note, pd, disease in rows:
            if plant.id in by_plant:
                continue  # abbiamo già preso la più recente grazie all'order_by

            by_plant[plant.id] = {
                "plant": {
                    "id": plant.id,
                    "scientific_name": plant.scientific_name,
                    "common_name": getattr(plant, "common_name", None),
                    "location_note": location_note,
                },
                "last_disease": {
                    "id": pd.id if pd else None,
                    "name": disease.name if disease else None,
                    "status": pd.status if pd else None,
                    "severity": pd.severity if pd else None,
                    "detected_at": (
                        pd.detected_at.isoformat() if (pd and pd.detected_at) else None
                    ),
                },
            }

        return jsonify(list(by_plant.values())), 200


@api_blueprint.route("/user/plants/healthy", methods=["GET"])
@require_jwt
def get_user_healthy_plants():
    """
    Restituisce tutte le piante dell'utente che hanno health_status='healthy'
    (campo su UserPlant).
    """
    user_id = g.user_id

    with _session_ctx() as s:
        q = (
            s.query(Plant, UserPlant.location_note)
            .join(UserPlant, UserPlant.plant_id == Plant.id)
            .filter(
                UserPlant.user_id == user_id,
                UserPlant.health_status == "healthy",
            )
            .order_by(Plant.common_name, Plant.scientific_name)
        )

        rows = q.all()

        result = []
        for plant, location_note in rows:
            result.append({
                "id": plant.id,
                "scientific_name": plant.scientific_name,
                "common_name": getattr(plant, "common_name", None),
                "location_note": location_note,
            })

        return jsonify(result), 200


@api_blueprint.route("/plant/full/<plant_id>", methods=["GET"])
@require_jwt
def get_full_plant(plant_id):
    with _session_ctx() as s:
        row = (
            s.query(Plant)
            .options(
                selectinload(Plant.photos),
                selectinload(Plant.family),
            )
            .filter(Plant.id == plant_id)
            .first()
        )

        if not row:
            return jsonify({"error": "Plant not found"}), 404

        return jsonify(_serialize_full_plant(row)), 200


# ========= CREATE Plant (PlantNet + defaults + watering plan) =========
@api_blueprint.route("/plant/add", methods=["POST"])
@require_jwt
def create_plant():
    print("\n================== [create_plant] RICHIESTA ARRIVATA ==================\n")

    # LOG PRIMA DI PARSARE
    try:
        raw = request.get_data()
        print(f"[DEBUG] request.get_data() LENGTH = {len(raw)}")
        print(f"[DEBUG] request.get_data() FIRST 300 CHARS = {raw[:300]}")
    except Exception as e:
        print(f"[DEBUG] ERROR WHILE READING RAW BODY: {e}")

    print("[DEBUG] Avvio _parse_json_body()…")

    # =====================================================================
    # 1) PARSE JSON BODY
    # =====================================================================
    try:
        body = _parse_json_body()
        print("[DEBUG] JSON PARSATO CORRETTAMENTE")
        print("[DEBUG] BODY:", body)
    except Exception as e:
        print("[ERRORE] _parse_json_body() ha fallito:", e)
        return jsonify({"error": "Invalid JSON"}), 400

    # =====================================================================
    # 2) RECUPERO BASE64
    # =====================================================================
    print("[DEBUG] Controllo campo image…")

    image_b64 = body.get("image")
    if not image_b64:
        print("[ERRORE] Image non presente nel body JSON")
        return jsonify({"error": "Field 'image' is required"}), 400

    print(f"[DEBUG] Lunghezza Base64 ricevuta = {len(image_b64)}")

    # =====================================================================
    # 3) BASE64 → BYTES
    # =====================================================================
    print("[DEBUG] Decodifica base64…")

    try:
        image_bytes = base64.b64decode(image_b64)
        print(f"[DEBUG] Base64 decodificato. Bytes = {len(image_bytes)}")
    except Exception as e:
        print("[ERRORE] Base64 non valido:", e)
        return jsonify({"error": "Invalid base64 image data"}), 400

    # wrapper compatibile col servizio
    class _FileWrapper:
        def __init__(self, b: bytes):
            self.stream = io.BytesIO(b)

    fake_file = _FileWrapper(image_bytes)
    print("[DEBUG] _FileWrapper creato correttamente")

    # =====================================================================
    # 4) CHIAMATA A PLANTNET
    # =====================================================================
    print("[DEBUG] → Invio immagine a PlantNet…")

    try:
        plant_info = image_service.process_image(fake_file)
        print("[DEBUG] ← Risposta da PlantNet:", plant_info)
    except Exception as e:
        print("[ERRORE] PlantNet FALLITA:", e)
        return jsonify({"error": "Image processing failed"}), 500

    if not plant_info or not plant_info.get("scientific_name"):
        print("[ERRORE] Nessun match da PlantNet")
        return jsonify({"error": "No plant match found from PlantNet"}), 422

    scientific_name = plant_info["scientific_name"]
    family_name = plant_info.get("family_name")

    print(f"[DEBUG] scientific_name = {scientific_name}")
    print(f"[DEBUG] family_name (PlantNet) = {family_name}")

    # =====================================================================
    # 5) DEFAULTS
    # =====================================================================
    print("[DEBUG] Carico defaults repository…")

    defaults = repo.get_plant_defaults(scientific_name) or {}
    print("[DEBUG] Defaults caricati:", defaults)

    # Base payload: scientific_name + tutto ciò che il JSON conosce
    payload = {
        "scientific_name": scientific_name,
        **{k: v for k, v in defaults.items() if v is not None},
    }

    print("[DEBUG] Payload iniziale:", payload)

    # =====================================================================
    # 6) ID + TIMESTAMPS
    # =====================================================================
    cols = _model_columns(Plant)
    now = datetime.utcnow()

    if "id" in cols and "id" not in payload:
        payload["id"] = str(uuid.uuid4())

    payload["created_at"] = now
    payload["updated_at"] = now

    print("[DEBUG] Payload con ID + timestamps:", payload)

    # =====================================================================
    # 7) NORMALIZZAZIONI CAMPI
    # =====================================================================
    print("[DEBUG] Normalizzazione campi NOT NULL…")

    # use
    if "use" in cols:
        raw_use = payload.get("use", defaults.get("use"))
        if isinstance(raw_use, list):
            raw_use = ", ".join(str(u) for u in raw_use if u)
        if raw_use is None:
            raw_use = ""
        payload["use"] = str(raw_use)

    # category
    if "category" in cols:
        raw_cat = payload.get("category", defaults.get("category"))
        if raw_cat is None:
            raw_cat = ""
        payload["category"] = str(raw_cat)

    # climate
    if "climate" in cols:
        raw_clim = payload.get("climate", defaults.get("climate"))
        if raw_clim is None:
            raw_clim = ""
        payload["climate"] = str(raw_clim)

    # livelli acqua/luce
    if "water_level" in cols and payload.get("water_level") is None:
        payload["water_level"] = defaults.get("water_level", 3)
    if "light_level" in cols and payload.get("light_level") is None:
        payload["light_level"] = defaults.get("light_level", 3)

    # difficulty
    if "difficulty" in cols and payload.get("difficulty") is None:
        payload["difficulty"] = defaults.get("difficulty", 3)

    # temp min/max
    if "min_temp_c" in cols and payload.get("min_temp_c") is None:
        tempmin = defaults.get("tempmin") or {}
        payload["min_temp_c"] = tempmin.get("celsius", 15)

    if "max_temp_c" in cols and payload.get("max_temp_c") is None:
        tempmax = defaults.get("tempmax") or {}
        payload["max_temp_c"] = tempmax.get("celsius", 25)

    # pests
    if "pests" in cols and payload.get("pests") is None:
        insects = defaults.get("insects")
        if insects is not None:
            payload["pests"] = insects

    print("[DEBUG] Payload dopo normalizzazione:", payload)

    # =====================================================================
    # 8) VALIDAZIONE NUMERICA
    # =====================================================================
    print("[DEBUG] Validazione numerica…")

    try:
        wl = int(payload["water_level"])
        ll = int(payload["light_level"])
        if not (1 <= wl <= 5) or not (1 <= ll <= 5):
            print("[ERRORE] Valori acqua/luce fuori range")
            return jsonify({"error": "water_level/light_level must be in [1..5]"}), 400
        payload["water_level"] = wl
        payload["light_level"] = ll
    except Exception as e:
        print("[ERRORE] Valori numerici acqua/luce non validi:", e)
        return jsonify({"error": "water_level/light_level must be integer"}), 400

    try:
        tmin = int(payload["min_temp_c"])
        tmax = int(payload["max_temp_c"])
        if tmin >= tmax:
            return jsonify({"error": "min_temp_c must be < max_temp_c"}), 400
        payload["min_temp_c"] = tmin
        payload["max_temp_c"] = tmax
    except Exception as e:
        print("[ERRORE] Temp non valide:", e)
        return jsonify({"error": "min_temp_c/max_temp_c must be integer"}), 400

    print("[DEBUG] Payload validato:", payload)

    # =====================================================================
    # 9) FILTRAGGIO MODELLO
    # =====================================================================
    data = _filter_fields_for_model(payload, Plant)
    print("[DEBUG] Payload finale per DB:", data)

    # =====================================================================
    # 10) TRANSAZIONE DB
    # =====================================================================
    print("[DEBUG] Apertura transazione DB…")

    with _session_ctx() as s:
        try:
            # family
            print("[DEBUG] Risoluzione family…")

            fam_id = None
            if family_name:
                fam_id = repo.get_family_by_name(family_name)
                print("[DEBUG] family da PlantNet:", fam_id)

            if not fam_id:
                fam_id = repo.get_family(data["scientific_name"])
                print("[DEBUG] family da defaults JSON:", fam_id)

            if not fam_id:
                print("[ERRORE] Family non trovata")
                return jsonify({"error": "Family not found"}), 400

            data["family_id"] = fam_id

            # create plant
            print("[DEBUG] Creazione pianta nel DB…")
            p = Plant(**data)
            s.add(p)
            _commit_or_409(s)
            print(f"[DEBUG] Pianta creata ID={p.id}")

            write_changes_upsert("plant", [_serialize_instance(p)])

            # ================================================================
            #  SALVATAGGIO IMMAGINE SU FILESYSTEM + RECORD PlantPhoto
            # ================================================================
            try:
                plant_id = str(p.id)

                base_dir = os.path.join("uploads", plant_id)
                os.makedirs(base_dir, exist_ok=True)

                photo_id = str(uuid.uuid4())
                filename = f"{photo_id}.jpg"
                image_path = os.path.join(base_dir, filename)

                # Salva il file sul filesystem
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                print(f"[DEBUG] Immagine salvata in: {image_path}")

                # Crea la riga in plant_photo
                photo = PlantPhoto(
                    id=photo_id,
                    plant_id=plant_id,
                    url=filename,  # nel DB salvo SOLO il nome file
                    caption=None,
                    order_index=0,
                )
                s.add(photo)

                # (opzionale) log per replay_changes
                write_changes_upsert("plant_photo", [_serialize_instance(photo)])

            except Exception as e:
                print(f"[ERRORE] Salvataggio immagine/PlantPhoto fallito: {e}")
            # ================================================================

            # LINK USER → PLANT (SEMPRE)
            print("[DEBUG] Creo link user-plant…")
            repo.ensure_user_plant_link(
                user_id=g.user_id,
                plant_id=str(p.id),
                location_note=None,
                since=datetime.now(),
                overwrite=False,
            )

            # ================================================================
            # WATERING PLAN (NON DEVE MAI ROMPERE NULLA)
            # ================================================================
            print("[DEBUG] Creo watering plan da questionario + pianta…")
            try:
                # usa il ReminderService istanziato in alto:
                # reminder_service = ReminderService()
                reminder_service.create_plan_for_new_plant(
                    user_id=str(g.user_id),
                    plant_id=str(p.id),
                )
                print("[DEBUG] Watering plan creato/aggiornato")
            except Exception as e:
                # qui logghiamo SOLO l'errore, ma NON facciamo rollback
                print("[ERRORE] Creazione watering plan fallita (ignoro):", e)

            # ================================================================
            # COMMIT FINALE — SALVA TUTTO SENZA ROLLBACK
            # ================================================================
            s.commit()

            print("\n================== [create_plant] COMPLETATA ==================\n")

            return jsonify({"ok": True, "id": str(p.id)}), 201

        except Exception as e:
            print(f"[ERRORE GENERALE DB] {e}")
            s.rollback()
            return jsonify({"error": f"DB error: {e}"}), 500


# ========= UPDATE Plant =========
@api_blueprint.route("/plant/update/<plant_id>", methods=["PATCH", "PUT"])
def update_plant(plant_id: str):
    if not plant_id:
        return jsonify({"error": "missing plant_id"}), 400
    _ensure_uuid(plant_id, "plant_id")
    payload = _parse_json_body()

    # --- size in update: if provided, validate and convert to Enum ---
    if "size" in payload and payload["size"] is not None:
        size_val = str(payload["size"])
        if size_val not in ALLOWED_SIZES:
            return jsonify({"error": f"size must be one of {sorted(ALLOWED_SIZES)}"}), 400
        payload["size"] = SizeEnum(size_val)

    with _session_ctx() as s:
        p = s.get(Plant, plant_id)
        if p is None:
            return jsonify({"error": "Plant not found"}), 404

        allowed = [
            "scientific_name", "common_name", "use", "origin",
            "water_level", "light_level", "min_temp_c", "max_temp_c",
            "category", "climate", "pests", "family_id",
            "size",  # <--- added
        ]
        for k, v in _filter_fields_for_model(payload, Plant).items():
            if k in allowed:
                setattr(p, k, v)

        p.updated_at = datetime.utcnow()
        _commit_or_409(s)

        write_changes_upsert("plant", [_serialize_instance(p)])
        return jsonify({"ok": True, "id": str(p.id)}), 200


# ========= DELETE Plant =========
@api_blueprint.route("/plant/delete/<plant_id>", methods=["DELETE"])
def delete_plant(plant_id: str):
    if not plant_id:
        return jsonify({"error": "missing plant_id"}), 400
    _ensure_uuid(plant_id, "plant_id")

    with _session_ctx() as s:
        p = s.get(Plant, plant_id)
        if p is not None:
            s.delete(p)
            _commit_or_409(s)
        write_changes_delete("plant", plant_id)
        return ("", 204)


# ========= Family =========
@api_blueprint.route("/family/all", methods=["GET"])
def family_all():
    with _session_ctx() as s:
        rows = s.query(Family).order_by(Family.name.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/family/add", methods=["POST"])
@require_jwt
def family_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Family)
    if not data.get("name"):
        return jsonify({"error": "Field 'name' is required"}), 400
    with _session_ctx() as s:
        f = Family(**data)
        s.add(f)
        _commit_or_409(s)
        write_changes_upsert("family", [_serialize_instance(f)])
        return jsonify({"ok": True, "id": f.id}), 201


@api_blueprint.route("/family/update/<fid>", methods=["PATCH", "PUT"])
@require_jwt
def family_update(fid: str):
    _ensure_uuid(fid, "family_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        f = s.get(Family, fid)
        if not f: return jsonify({"error": "Family not found"}), 404
        for k, v in _filter_fields_for_model(payload, Family).items():
            setattr(f, k, v)
        _commit_or_409(s)
        write_changes_upsert("family", [_serialize_instance(f)])
        return jsonify({"ok": True, "id": f.id}), 200


@api_blueprint.route("/family/delete/<fid>", methods=["DELETE"])
@require_jwt
def family_delete(fid: str):
    _ensure_uuid(fid, "family_id")
    with _session_ctx() as s:
        f = s.get(Family, fid)
        if f:
            s.delete(f)
            _commit_or_409(s)
        write_changes_delete("family", fid)
        return ("", 204)


@api_blueprint.route("/plants/by-size/<size>", methods=["GET"])
def plants_by_size(size: str):
    """
    Returns all plants with the specified size.
    size ∈ {small, medium, large, giant}
    """
    if not size or size not in ALLOWED_SIZES:
        return jsonify({"error": f"size must be one of {sorted(ALLOWED_SIZES)}"}), 400

    with _session_ctx() as s:
        rows = (
            s.query(Plant)
            .filter(Plant.size == SizeEnum(size))
            .order_by(Plant.scientific_name.asc())
            .all()
        )
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/plants/by-use/<use>", methods=["GET"])
def plants_by_use(use: str):
    """
    Returns all plants with the given 'use' (case-insensitive match).
    Examples of use: 'ornamental', 'medicinal', etc.
    """
    if not use:
        return jsonify({"error": "Missing 'use' parameter"}), 400

    use_norm = use.strip().lower()
    with _session_ctx() as s:
        rows = (
            s.query(Plant)
            .filter(func.lower(Plant.use) == use_norm)
            .order_by(Plant.scientific_name.asc())
            .all()
        )
        return jsonify([_serialize_instance(r) for r in rows]), 200


# ========= PlantPhoto =========
@api_blueprint.route("/plant_photo/all", methods=["GET"])
@require_jwt
def plant_photo_all():
    with _session_ctx() as s:
        rows = s.query(PlantPhoto).order_by(PlantPhoto.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/plant/photo/add/<plant_id>", methods=["POST"])
@require_jwt
def plant_photo_add(plant_id: str):
    _ensure_uuid(plant_id, "plant_id")
    payload = _parse_json_body()
    data = _filter_fields_for_model({**payload, "plant_id": plant_id}, PlantPhoto)
    if not data.get("url"):
        return jsonify({"error": "url required"}), 400
    with _session_ctx() as s:
        ph = PlantPhoto(**data)
        s.add(ph)
        _commit_or_409(s)
        write_changes_upsert("plant_photo", [_serialize_instance(ph)])
        return jsonify({"ok": True, "id": ph.id}), 201


@api_blueprint.route("/plant/photo/update/<photo_id>", methods=["PATCH", "PUT"])
@require_jwt
def plant_photo_update(photo_id: str):
    _ensure_uuid(photo_id, "photo_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        ph = s.get(PlantPhoto, photo_id)
        if not ph: return jsonify({"error": "PlantPhoto not found"}), 404
        for k, v in _filter_fields_for_model(payload, PlantPhoto).items():
            setattr(ph, k, v)
        _commit_or_409(s)
        write_changes_upsert("plant_photo", [_serialize_instance(ph)])
        return jsonify({"ok": True, "id": ph.id}), 200


@api_blueprint.route("/plant-photo/delete/<photo_id>", methods=["DELETE"])
@require_jwt
def plant_photo_delete(photo_id: str):
    """
    Deletes the plant photo:
    - removes the row from plant_photo
    - attempts to delete the file on disk (if exists)
    - updates changes.json with a delete
    Returns: 204 (idempotent)
    """
    with _session_ctx() as s:
        pp = s.get(PlantPhoto, photo_id)

        if pp and pp.url and pp.url.startswith("/uploads/"):
            try:
                rel = pp.url[len("/uploads/"):]
                base = os.path.realpath(current_app.config["UPLOAD_DIR"])
                full = os.path.realpath(os.path.join(base, rel))
                if full.startswith(base) and os.path.exists(full):
                    os.remove(full)
                    dirpath = os.path.dirname(full)
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
            except Exception as e:
                current_app.logger.warning(f"Unable to remove file for photo_id={photo_id}: {e}")

        if pp:
            s.delete(pp)
            _commit_or_409(s)

    write_changes_delete("plant_photo", photo_id)
    return ("", 204)


# ========= Disease =========
@api_blueprint.route("/disease/all", methods=["GET"])
def disease_all():
    with _session_ctx() as s:
        rows = s.query(Disease).order_by(Disease.name.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/disease/add", methods=["POST"])
@require_jwt
def disease_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Disease)
    if not data.get("name") or not data.get("description"):
        return jsonify({"error": "name and description required"}), 400
    with _session_ctx() as s:
        d = Disease(**data)
        s.add(d)
        _commit_or_409(s)
        write_changes_upsert("disease", [_serialize_instance(d)])
        return jsonify({"ok": True, "id": d.id}), 201


@api_blueprint.route("/disease/update/<did>", methods=["PATCH", "PUT"])
@require_jwt
def disease_update(did: str):
    _ensure_uuid(did, "disease_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        d = s.get(Disease, did)
        if not d: return jsonify({"error": "Disease not found"}), 404
        for k, v in _filter_fields_for_model(payload, Disease).items():
            setattr(d, k, v)
        _commit_or_409(s)
        write_changes_upsert("disease", [_serialize_instance(d)])
        return jsonify({"ok": True, "id": d.id}), 200


@api_blueprint.route("/disease/delete/<did>", methods=["DELETE"])
@require_jwt
def disease_delete(did: str):
    _ensure_uuid(did, "disease_id")
    with _session_ctx() as s:
        d = s.get(Disease, did)
        if d:
            s.delete(d)
            _commit_or_409(s)
        write_changes_delete("disease", did)
        return ("", 204)


@api_blueprint.route("/ai/model/check-plant-disease", methods=["POST"])
@require_jwt
def ai_model_check_plant_disease():
    body = request.get_json(silent=True) if request.is_json else None

    # 1) unknown_threshold come nell'altro endpoint
    try:
        raw_thr = request.values.get("unknown_threshold")
        if raw_thr is None and isinstance(body, dict):
            raw_thr = body.get("unknown_threshold")
        unknown_threshold = _parse_unknown_threshold(raw_thr)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # 2) family (può arrivare dal client oppure dal DB più avanti)
    family = request.values.get("family") or (body.get("family") if isinstance(body, dict) else None)

    # 3) disease_suggestions (form + JSON)
    disease_suggestions: list[str] = []
    if request.values:
        disease_suggestions.extend([v for v in request.values.getlist("disease_suggestions") if v])
    if isinstance(body, dict):
        raw = body.get("disease_suggestions")
        if isinstance(raw, list):
            disease_suggestions.extend([str(v) for v in raw if v is not None])

    # 4) plant_id dal body (form o JSON)
    plant_id = request.values.get("plant_id") or (body.get("plant_id") if isinstance(body, dict) else None)
    if not plant_id:
        return jsonify({"error": "Missing 'plant_id' in request."}), 400

    _ensure_uuid(plant_id, "plant_id")

    with _session_ctx() as s:
        # Controllo pianta
        plant = s.get(Plant, plant_id)
        if not plant:
            return jsonify({"error": "Plant not found"}), 404

        # Controllo che l'utente la possieda e recupero la UserPlant
        up = s.get(UserPlant, (g.user_id, plant_id))
        if not up:
            return jsonify({"error": "Forbidden: you do not own this plant"}), 403

        # Se family non è passato, prendo dal DB
        if not family and plant.family:
            family = plant.family.name

        # --- Recupero dell'immagine ---
        # Se il client manda una nuova immagine, uso quella;
        # altrimenti uso la prima PlantPhoto salvata.
        need_close = False
        if "image" in request.files:
            image_file = request.files["image"]
        else:
            photos = plant.photos or []
            if not photos:
                return jsonify({"error": "Plant has no photos to run disease detection"}), 400

            photo = photos[0]  # prima foto (grazie all'order_by su relationship)
            filename_only = os.path.basename(photo.url)

            upload_root = current_app.config.get("UPLOAD_DIR") or UPLOAD_FOLDER
            image_path = os.path.join(upload_root, plant_id, filename_only)

            if not os.path.exists(image_path):
                return jsonify({"error": "Image file not found on disk for this plant"}), 500

            image_file = open(image_path, "rb")
            need_close = True

        # 5) Chiamata al servizio di disease recognition
        try:
            raw_result, label, prob = image_service.disease_detection_top_class(
                image_file=image_file,
                unknown_threshold=unknown_threshold,
                family=family,
                disease_suggestions=disease_suggestions or None,
            )
        except ValueError as exc:
            if need_close:
                image_file.close()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            if need_close:
                image_file.close()
            current_app.logger.exception("Disease model failed: %s", exc)
            return jsonify({"error": f"Inference failed: {exc}"}), 502
        finally:
            if need_close:
                image_file.close()

        # --- DECISIONE: è malata o no? ---
        # Regola:
        # - se label == "healthy" OR prob < DISEASE_PROB_THRESHOLD -> pianta considerata sana
        #   (non inseriamo nulla in Disease/PlantDisease)
        if label == "healthy" or prob < DISEASE_PROB_THRESHOLD:
            # Aggiorno lo stato sulla UserPlant
            up.health_status = "healthy"  # oppure HealthStatus.HEALTHY.value
            _commit_or_409(s)

            return jsonify({
                "plant_id": plant_id,
                "status": "healthy_plant",
                "threshold": DISEASE_PROB_THRESHOLD,
                "top_prediction": {
                    "label": label,
                    "probability": prob,
                },
                "model_raw": raw_result,
            }), 200

        # Da qui in poi:
        # - label != "healthy"
        # - prob >= DISEASE_PROB_THRESHOLD
        # => malattia "significativa", la salviamo.

        # 6) Dettagli malattia dal JSON a partire da family + label
        fam_key = family or (plant.family.name if plant.family else None)
        disease_info = None
        if fam_key and fam_key in PLANT_DISEASE_DETAILS:
            disease_info = PLANT_DISEASE_DETAILS[fam_key].get(label)

        if not disease_info:
            disease_info = {
                "name": label,
                "description": f"Disease detected by AI model ({label})",
                "cure_tips": None,
            }

        # 7) Upsert Disease
        disease = (
            s.query(Disease)
            .filter(Disease.name == disease_info["name"])
            .one_or_none()
        )
        if not disease:
            cure_tips = disease_info.get("cure_tips")
            if isinstance(cure_tips, list):
                treatment_text = "\n".join(cure_tips)
            else:
                treatment_text = cure_tips

            disease = Disease(
                name=disease_info["name"],
                description=disease_info["description"],
                treatment=treatment_text,
            )
            s.add(disease)
            s.flush()
            write_changes_upsert("disease", [_serialize_instance(disease)])

        # 8) PlantDisease: SOLO se prob >= threshold
        severity = int(round(prob * 100))
        status = "confirmed"  # perché siamo sopra soglia

        pd = PlantDisease(
            plant_id=plant_id,
            disease_id=disease.id,
            detected_at=datetime.utcnow().date(),
            severity=severity,
            notes=f"Detected by AI disease model (raw_label={label}, prob={prob:.3f})",
            status=status,
        )
        s.add(pd)

        # Aggiorno anche lo stato sulla UserPlant
        up.health_status = "sick"  # oppure HealthStatus.SICK.value

        _commit_or_409(s)
        write_changes_upsert("plant_disease", [_serialize_instance(pd)])

        return jsonify({
            "plant_id": plant_id,
            "status": "sick_plant",
            "threshold": DISEASE_PROB_THRESHOLD,
            "top_prediction": {
                "label": label,
                "probability": prob,
            },
            "disease": {
                "id": disease.id,
                "name": disease.name,
                "status": status,
                "severity": severity,
            },
            "model_raw": raw_result,
        }), 200


# ========= PlantDisease =========
@api_blueprint.route("/plant_disease/all", methods=["GET"])
@require_jwt
def plant_disease_all():
    with _session_ctx() as s:
        rows = s.query(PlantDisease).order_by(PlantDisease.detected_at.desc().nulls_last()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/plant_disease/add", methods=["POST"])
@require_jwt
def plant_disease_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, PlantDisease)

    required = ["plant_id", "disease_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400

    with _session_ctx() as s:
        if not s.get(UserPlant, (g.user_id, data["plant_id"])):
            return jsonify({"error": "Forbidden: non possiedi questa pianta"}), 403

        pd = PlantDisease(**data)
        s.add(pd)
        _commit_or_409(s)
        write_changes_upsert("plant_disease", [_serialize_instance(pd)])
        return jsonify({"ok": True, "id": pd.id}), 201


@api_blueprint.route("/plant_disease/update/<pdid>", methods=["PATCH", "PUT"])
@require_jwt
def plant_disease_update(pdid: str):
    _ensure_uuid(pdid, "plant_disease_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        pd = s.get(PlantDisease, pdid)
        if not pd: return jsonify({"error": "PlantDisease not found"}), 404
        for k, v in _filter_fields_for_model(payload, PlantDisease).items():
            setattr(pd, k, v)
        _commit_or_409(s)
        write_changes_upsert("plant_disease", [_serialize_instance(pd)])
        return jsonify({"ok": True, "id": pd.id}), 200


@api_blueprint.route("/plant_disease/delete/<pdid>", methods=["DELETE"])
@require_jwt
def plant_disease_delete(pdid: str):
    _ensure_uuid(pdid, "plant_disease_id")
    with _session_ctx() as s:
        pd = s.get(PlantDisease, pdid)
        if pd:
            s.delete(pd)
            _commit_or_409(s)
        write_changes_delete("plant_disease", pdid)
        return ("", 204)


# ========= User =========
@api_blueprint.route("/user/all", methods=["GET"])
@require_jwt
def user_all():
    with _session_ctx() as s:
        rows = s.query(User).order_by(User.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/user/add", methods=["POST"])
def user_add():
    payload = _parse_json_body()

    # se c'è "password" la trasformiamo in "password_hash"
    if "password" in payload:
        payload["password_hash"] = generate_password_hash(payload.pop("password"))

    data = _filter_fields_for_model(payload, User)
    required = ["email", "password_hash", "first_name", "last_name"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Mandatory fields: {', '.join(missing)}"}), 400

    with _session_ctx() as s:
        u = User(**data)
        s.add(u)
        _commit_or_409(s)
        write_changes_upsert("user", [_serialize_instance(u)])

        # GENERATE JWT (access token)
        access_token = generate_token(str(u.id))

        return jsonify({
            "ok": True,

            # ID utente
            "id": str(u.id),
            "user_id": str(u.id),

            # nome/cognome in vari formati
            "name": u.first_name,  # per retrocompatibilità
            "surname": u.last_name,  # per retrocompatibilità
            "first_name": u.first_name,
            "last_name": u.last_name,

            # token in entrambi i campi che il client si aspetta
            "access_token": access_token,
            "token": access_token,

            # oggetto user completo, utile per il client
            "user": {
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
            },
        }), 201


@api_blueprint.route("/user/update", methods=["PATCH", "PUT"])
@require_jwt
def user_update():
    uid = g.user_id  # <-- PRENDI ID DAL TOKEN
    payload = _parse_json_body()

    if payload.get("password"):
        payload["password_hash"] = generate_password_hash(payload.pop("password"))

    with _session_ctx() as s:
        u = s.get(User, uid)
        if not u:
            return jsonify({"error": "User not found"}), 404

        for k, v in _filter_fields_for_model(payload, User).items():
            setattr(u, k, v)

        u.updated_at = datetime.utcnow()
        _commit_or_409(s)
        write_changes_upsert("user", [_serialize_instance(u)])

        return jsonify({"ok": True, "id": u.id}), 200


@api_blueprint.route("/user/delete-me", methods=["DELETE"])
@require_jwt
def user_delete_me():
    """
    Cancella l'account dell'utente loggato (g.user_id) e tutti i dati collegati.
    Logga inoltre le delete in changes.json.
    """
    current_user_id = getattr(g, "user_id", None)
    if not current_user_id:
        return jsonify({"error": "Unauthorized"}), 401

    orphan_plant_ids: list[str] = []
    orphan_photo_ids: list[str] = []
    user_plant_pairs: list[dict] = []

    with _session_ctx() as s:
        u = s.get(User, current_user_id)
        if not u:
            return jsonify({"error": "User non trovato"}), 404

        up_rows = (
            s.query(UserPlant)
            .filter(UserPlant.user_id == current_user_id)
            .all()
        )
        for up in up_rows:
            user_plant_pairs.append({
                "user_id": up.user_id,
                "plant_id": up.plant_id,
                "_delete": True,
            })
        plant_ids = [up.plant_id for up in up_rows]

        if plant_ids:
            counts = (
                s.query(UserPlant.plant_id, func.count(UserPlant.user_id))
                .filter(UserPlant.plant_id.in_(plant_ids))
                .group_by(UserPlant.plant_id)
                .all()
            )
            orphan_plant_ids = [pid for (pid, cnt) in counts if cnt == 1]

        if orphan_plant_ids:
            photos = (
                s.query(PlantPhoto)
                .filter(PlantPhoto.plant_id.in_(orphan_plant_ids))
                .all()
            )

            base = os.path.realpath(current_app.config["UPLOAD_DIR"])
            for pp in photos:
                orphan_photo_ids.append(pp.id)
                if pp.url and pp.url.startswith("/uploads/"):
                    try:
                        rel = pp.url[len("/uploads/"):]
                        full = os.path.realpath(os.path.join(base, rel))
                        if full.startswith(base) and os.path.exists(full):
                            os.remove(full)
                            dirpath = os.path.dirname(full)
                            try:
                                os.rmdir(dirpath)
                            except OSError:
                                pass
                    except Exception as e:
                        current_app.logger.warning(
                            f"Impossibile rimuovere file per photo_id={pp.id}: {e}"
                        )

            for pid in orphan_plant_ids:
                plant = s.get(Plant, pid)
                if plant:
                    s.delete(plant)

        s.delete(u)
        _commit_or_409(s)

    write_changes_delete("user", current_user_id)

    if user_plant_pairs:
        write_changes_upsert("user_plant", user_plant_pairs)

    for pid in orphan_plant_ids:
        write_changes_delete("plant", pid)

    for photo_id in orphan_photo_ids:
        write_changes_delete("plant_photo", photo_id)

    return ("", 204)


# ========= UserPlant (composite PK: user_id + plant_id) =========
@api_blueprint.route("/user_plant/all", methods=["GET"])
@require_jwt
def user_plant_all():
    """
    Restituisce SOLO le piante del giardino dell'utente loggato.
    """
    user_id = g.user_id  # preso dal JWT

    with _session_ctx() as s:
        rows = (
            s.query(UserPlant)
            .options(
                selectinload(UserPlant.plant).selectinload(Plant.photos)
            )
            .filter(UserPlant.user_id == user_id)
            .all()
        )

        return jsonify([_serialize_with_relations(r) for r in rows]), 200


@api_blueprint.route("/user_plant/add", methods=["POST"])
@require_jwt
def user_plant_add():
    payload = _parse_json_body()
    plant_id = (payload.get("plant_id") or "").strip()
    if not plant_id:
        return jsonify({"error": "Required field: plant_id"}), 400
    _ensure_uuid(plant_id, "plant_id")

    with _session_ctx() as s:
        if s.get(UserPlant, (g.user_id, plant_id)):
            return jsonify({"ok": True}), 200

        up = UserPlant(
            user_id=g.user_id,
            plant_id=plant_id,
            location_note=payload.get("location_note"),
            since=payload.get("since"),
        )
        s.add(up)
        _commit_or_409(s)
        write_changes_upsert("user_plant", [_serialize_instance(up)])
        return jsonify({"ok": True}), 201


@api_blueprint.route("/user_plant/delete", methods=["DELETE"])
@require_jwt
def user_plant_delete():
    user_id = request.args.get("user_id")
    plant_id = request.args.get("plant_id")
    if not user_id or not plant_id:
        return jsonify({"error": "user_id and plant_id are required"}), 400
    _ensure_uuid(user_id, "user_id")
    _ensure_uuid(plant_id, "plant_id")
    with _session_ctx() as s:
        row = s.get(UserPlant, (user_id, plant_id))
        if row:
            s.delete(row)
            _commit_or_409(s)
        write_changes_upsert("user_plant", [{"user_id": user_id, "plant_id": plant_id, "_delete": True}])
        return ("", 204)


# ============================
#         FRIENDSHIP
# ============================

@api_blueprint.route("/friendship/summary", methods=["GET"])
@require_jwt
def friendship_summary():
    user_id = g.user_id
    print("\n===== [API] friendship_summary CALLED =====")
    print(f"[USER]  Logged user_id: {user_id}")

    repo = RepositoryService()

    # short_id dell’utente loggato
    short_id = user_id.split("-")[0]
    print(f"[USER]  short_id (self): {short_id}")

    # Tutte le friendship dell'utente
    rows = repo.get_friendships_for_user(user_id)
    print(f"[DB]    Found {len(rows)} friendship rows for user {user_id}")

    friends_out = []
    user_cache = {}

    with repo.Session() as s:
        for fr in rows:
            print("\n--- Friendship Row ---")
            print(f"[FR] friendship_id={fr.id}")

            # Identifica l’amico
            friend_id = fr.user_id_b if fr.user_id_a == user_id else fr.user_id_a
            print(f"[FR] friend_id resolved: {friend_id}")

            # Carica info amico
            if friend_id not in user_cache:
                print(f"[DB] Fetching friend user from DB: {friend_id}")
                u = s.query(User).filter(User.id == friend_id).first()
                user_cache[friend_id] = u

                if u is None:
                    print(f"[WARN] Friend user not found in DB: {friend_id}")
                else:
                    print(f"[OK]   Loaded friend user: {u.first_name} {u.last_name}")
            else:
                print(f"[CACHE] Using cached user for {friend_id}")

            u = user_cache[friend_id]

            # Calcolo short_id dell’amico
            friend_short_id = friend_id.split("-")[0]
            print(f"[FR] friend_short_id: {friend_short_id}")

            # Aggiungi all’output
            out_entry = {
                "friendship_id": fr.id,
                "user_id": friend_id,
                "short_id": friend_short_id,
                "first_name": u.first_name if u else None,
                "last_name": u.last_name if u else None,
                "created_at": fr.created_at.isoformat() if fr.created_at else None,
            }

            print(f"[OUT] Appended friend entry: {out_entry}")

            friends_out.append(out_entry)

    print("\n===== FINAL OUTPUT =====")
    print(f"[RETURN] Total friends: {len(friends_out)}")
    for f in friends_out:
        print(f" → {f['first_name']} {f['last_name']} | user_id={f['user_id']} | short_id={f['short_id']}")

    print("===== END friendship_summary =====\n")

    return jsonify({
        "short_id": short_id,
        "my_friends": friends_out
    }), 200


# ============================
#   ADD FRIEND BY SHORT-ID
# ============================

@api_blueprint.route("/friendship/add-by-short", methods=["POST"])
@require_jwt
def friendship_add_by_short():
    payload = _parse_json_body()
    short_id = payload.get("short_id", "").strip()

    print(f"[API] /friendship/add-by-short short_id={short_id}")

    if not short_id or len(short_id) < 3:
        return jsonify({"error": "Invalid short_id"}), 400

    repo = RepositoryService()
    current_user_id = g.user_id
    print(f"[API] Current user = {current_user_id}")

    # 1) trova user dal short id
    target_user_id = repo.get_user_id_by_short(short_id)
    print(f"[API] get_user_id_by_short → {target_user_id}")

    if not target_user_id:
        return jsonify({"error": "User not found"}), 404

    if target_user_id == current_user_id:
        return jsonify({"error": "You cannot add yourself"}), 400

    # 2) esiste già una friendship?
    existing = repo.get_existing_friendship(current_user_id, target_user_id)
    if existing:
        return jsonify({"error": "Friendship already exists"}), 409

    # 3) crea friendship
    data = {
        "user_id_a": current_user_id,
        "user_id_b": target_user_id,
        "status": "accepted"
    }

    try:
        fr = repo.create_friendship(data)
        print(f"[API] Friendship created → {fr.id}")
        return jsonify({"ok": True, "friendship_id": fr.id}), 201

    except Exception as e:
        print("[API] ERROR creating friendship:", e)
        return jsonify({"error": "Could not create friendship"}), 500


# ============================
#      ADD FRIENDSHIP RAW
# ============================

@api_blueprint.route("/friendship/add", methods=["POST"])
@require_jwt
def friendship_add():
    payload = _parse_json_body()
    repo = RepositoryService()

    data = _filter_fields_for_model(payload, Friendship)
    required = ["user_id_a", "user_id_b", "status"]
    missing = [k for k in required if not data.get(k)]

    if missing:
        return jsonify({"error": f"Required fields: {', '.join(missing)}"}), 400

    try:
        fr = repo.create_friendship(data)
        print(f"[API] friendship_add → created {fr.id}")
    except Exception as e:
        print("[API] ERROR friendship_add:", e)
        return jsonify({"error": "Could not create friendship"}), 500

    return jsonify({"ok": True, "id": fr.id}), 201


# ============================
#     UPDATE FRIENDSHIP
# ============================

@api_blueprint.route("/friendship/update/<fid>", methods=["PATCH", "PUT"])
@require_jwt
def friendship_update(fid: str):
    _ensure_uuid(fid, "friendship_id")
    payload = _parse_json_body()
    repo = RepositoryService()

    fr = repo.get_friendship_by_id(fid)
    if not fr:
        return jsonify({"error": "Friendship not found"}), 404

    try:
        updated = repo.update_friendship(fid, payload)
        print(f"[API] friendship_update → updated {fid}")
    except Exception as e:
        print("[API] ERROR updating friendship:", e)
        return jsonify({"error": "Update error"}), 500

    return jsonify({"ok": True, "id": fid}), 200


# ============================
#      DELETE FRIENDSHIP
# ============================

@api_blueprint.route("/friendship/delete/<fid>", methods=["DELETE"])
@require_jwt
def friendship_delete(fid: str):
    _ensure_uuid(fid, "friendship_id")
    repo = RepositoryService()

    fr = repo.get_friendship_by_id(fid)
    if not fr:
        return jsonify({"error": "Friendship not found"}), 404

    try:
        repo.delete_friendship(fid)
        print(f"[API] friendship_delete → removed {fid}")
    except Exception as e:
        print("[API] ERROR deleting friendship:", e)
        return jsonify({"error": "Could not delete friendship"}), 500

    return ("", 204)


# ========= SharedPlant =========
@api_blueprint.route("/shared_plant/all", methods=["GET"])
@require_jwt
def shared_plant_all():
    user_id = g.user_id
    repo = RepositoryService()

    # Il repository restituisce già il JSON finale
    rows = repo.get_shared_plants_for_user(user_id)

    return jsonify(rows), 200


@api_blueprint.route("/shared_plant/add", methods=["POST"])
@require_jwt
def shared_plant_add():
    """
    Crea una nuova condivisione e assegna la pianta al recipient (tabella user_plant).
    """
    from datetime import datetime

    payload = _parse_json_body()
    repo = RepositoryService()

    plant_id = payload.get("plant_id")
    short_id = payload.get("short_id")

    print("\n===== [API] SHARED PLANT ADD =====")
    print(f"[PAYLOAD] plant_id={plant_id}, short_id={short_id}")

    # -------------------------
    # Validate input
    # -------------------------
    if not plant_id or not short_id:
        print("[ERROR] Missing plant_id or short_id")
        return jsonify({"error": "Missing plant_id or short_id"}), 400

    owner_id = g.user_id
    print(f"[OWNER] {owner_id}")

    # -------------------------
    # Check plant exists
    # -------------------------
    print("[CHECK] Verifying plant exists…")
    with repo.Session() as s:
        plant = s.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            print("[ERROR] Plant not found")
            return jsonify({"error": "Plant not found"}), 404

    # -------------------------
    # Resolve short_id → recipient
    # -------------------------
    recipient_id = repo.get_user_id_by_short(short_id)

    if not recipient_id:
        print("[ERROR] Recipient short_id not found")
        return jsonify({"error": "Recipient not found"}), 404

    print(f"[RECIPIENT] {recipient_id}")

    if recipient_id == owner_id:
        print("[ERROR] Cannot share with yourself")
        return jsonify({"error": "Cannot share with yourself"}), 400

    # -------------------------
    # Check duplicate shared plant
    # -------------------------
    print("[CHECK] Checking existing shared plants…")
    existing = repo.get_shared_plants_for_user(owner_id)

    for row in existing:
        if (
            row["owner_user_id"] == owner_id and
            row["recipient_user_id"] == recipient_id and
            row["plant_id"] == plant_id and
            row.get("ended_sharing_at") is None
        ):
            print("[ERROR] Already shared")
            return jsonify({"error": "Already shared"}), 409

    # -------------------------
    # Create SharedPlant
    # -------------------------
    data = {
        "owner_user_id": owner_id,
        "recipient_user_id": recipient_id,
        "plant_id": plant_id,
        "can_edit": True
    }

    try:
        sp = repo.create_shared_plant(data)
        print(f"[OK] SharedPlant created id={sp.id}")
    except Exception as e:
        print("[FATAL] Error creating shared plant:", e)
        return jsonify({"error": "Could not create shared plant"}), 500

    # -------------------------
    # Assign plant to recipient (user_plant)
    # -------------------------
    print("[CHECK] Assigning plant to recipient…")

    try:
        up = repo.ensure_user_plant_link(
            user_id=recipient_id,
            plant_id=plant_id,
            location_note=None,
            since=datetime.utcnow(),
            overwrite=False
        )
        print("[OK] UserPlant linked:", up)
    except Exception as e:
        print("[FATAL] Error linking plant to user:", e)
        return jsonify({
            "error": "Shared but could not assign plant to recipient (user_plant failed)"
        }), 500

    print("===== [API] FINISHED SHARED PLANT ADD =====\n")

    return jsonify({"ok": True, "shared_id": sp.id}), 201


@api_blueprint.route("/shared_plant/update/<sid>", methods=["PATCH", "PUT"])
@require_jwt
def shared_plant_update(sid: str):
    _ensure_uuid(sid, "shared_plant_id")
    payload = _parse_json_body()
    repo = RepositoryService()

    # tieni solo i campi validi per SharedPlant
    data = _filter_fields_for_model(payload, SharedPlant)

    sp = repo.update_shared_plant(sid, data)
    if not sp:
        return jsonify({"error": "SharedPlant not found"}), 404

    return jsonify({"ok": True, "id": sp.id}), 200


@api_blueprint.route("/shared_plant/delete/<sid>", methods=["DELETE"])
@require_jwt
def shared_plant_delete(sid: str):
    _ensure_uuid(sid, "shared_plant_id")
    repo = RepositoryService()

    ok = repo.delete_shared_plant(sid, g.user_id)

    if not ok:
        return jsonify({"error": "SharedPlant not found or unauthorized"}), 404

    return ("", 204)



# ========= WateringPlan =========
@api_blueprint.route("/plant/<plant_id>/watering-plan", methods=["GET"])
@require_jwt
def get_watering_plan_for_plant(plant_id: str):
    _ensure_uuid(plant_id, "plant_id")
    with _session_ctx() as s:
        wp = (
            s.query(WateringPlan)
            .filter(
                WateringPlan.user_id == g.user_id,
                WateringPlan.plant_id == plant_id,
            )
            .one_or_none()
        )
        if not wp:
            return jsonify({"error": "WateringPlan not found"}), 404

        return jsonify(_serialize_instance(wp)), 200


@api_blueprint.route("/watering_plan/all", methods=["GET"])
@require_jwt
def watering_plan_all():
    with _session_ctx() as s:
        rows = s.query(WateringPlan).order_by(WateringPlan.next_due_at.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/watering_plan/add", methods=["POST"])
@require_jwt
def watering_plan_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, WateringPlan)

    required = ["plant_id", "next_due_at", "interval_days"]  # user_id rimosso
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400

    with _session_ctx() as s:
        if not s.get(UserPlant, (g.user_id, data["plant_id"])):
            return jsonify({"error": "Forbidden: non possiedi questa pianta"}), 403

        data["user_id"] = g.user_id
        wp = WateringPlan(**data)
        s.add(wp)
        _commit_or_409(s)
        write_changes_upsert("watering_plan", [_serialize_instance(wp)])
        return jsonify({"ok": True, "id": wp.id}), 201


@api_blueprint.route("/watering_plan/update/<wid>", methods=["PATCH", "PUT"])
@require_jwt
def watering_plan_update(wid: str):
    _ensure_uuid(wid, "watering_plan_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        wp = s.get(WateringPlan, wid)
        if not wp: return jsonify({"error": "WateringPlan not found"}), 404
        for k, v in _filter_fields_for_model(payload, WateringPlan).items():
            setattr(wp, k, v)
        _commit_or_409(s)
        write_changes_upsert("watering_plan", [_serialize_instance(wp)])
        return jsonify({"ok": True, "id": wp.id}), 200


@api_blueprint.route("/watering_plan/delete/<wid>", methods=["DELETE"])
@require_jwt
def watering_plan_delete(wid: str):
    _ensure_uuid(wid, "watering_plan_id")
    with _session_ctx() as s:
        wp = s.get(WateringPlan, wid)
        if wp:
            s.delete(wp)
            _commit_or_409(s)
        write_changes_delete("watering_plan", wid)
        return ("", 204)


# ========= WateringLog =========
@api_blueprint.route("/watering_log/all", methods=["GET"])
@require_jwt
def watering_log_all():
    with _session_ctx() as s:
        rows = s.query(WateringLog).order_by(WateringLog.done_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/watering_log/add", methods=["POST"])
@require_jwt
def watering_log_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, WateringLog)

    required = ["plant_id", "done_at", "amount_ml"]  # user_id rimosso
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400

    with _session_ctx() as s:
        if not s.get(UserPlant, (g.user_id, data["plant_id"])):
            return jsonify({"error": "Forbidden: non possiedi questa pianta"}), 403

        data["user_id"] = g.user_id
        wl = WateringLog(**data)
        s.add(wl)
        _commit_or_409(s)
        write_changes_upsert("watering_log", [_serialize_instance(wl)])
        return jsonify({"ok": True, "id": wl.id}), 201


@api_blueprint.route("/watering_log/update/<lid>", methods=["PATCH", "PUT"])
@require_jwt
def watering_log_update(lid: str):
    _ensure_uuid(lid, "watering_log_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        wl = s.get(WateringLog, lid)
        if not wl: return jsonify({"error": "WateringLog not found"}), 404
        for k, v in _filter_fields_for_model(payload, WateringLog).items():
            setattr(wl, k, v)
        _commit_or_409(s)
        write_changes_upsert("watering_log", [_serialize_instance(wl)])
        return jsonify({"ok": True, "id": wl.id}), 200


@api_blueprint.route("/watering_log/delete/<lid>", methods=["DELETE"])
@require_jwt
def watering_log_delete(lid: str):
    _ensure_uuid(lid, "watering_log_id")
    with _session_ctx() as s:
        wl = s.get(WateringLog, lid)
        if wl:
            s.delete(wl)
            _commit_or_409(s)
        write_changes_delete("watering_log", lid)
        return ("", 204)


@api_blueprint.route("/question/all", methods=["GET"])
@require_jwt
def question_all():
    """
    Restituisce tutte le domande con le opzioni associate.
    (Endpoint "admin" / gestione, non legato a un singolo utente.)
    """
    with _session_ctx() as s:
        # se Question avesse created_at lo useremmo, altrimenti ordiniamo per id
        order_col = getattr(Question, "created_at", Question.id)
        rows = (
            s.query(Question)
            .filter(Question.active.is_(True))
            .order_by(order_col.desc())
            .all()
        )

        out = []
        for q in rows:
            opts = sorted(q.options, key=lambda o: o.position)
            out.append({
                "id": str(q.id),
                "text": q.text,
                "type": q.type,
                "active": q.active,
                "options": [
                    {
                        "id": str(o.id),
                        "label": o.label,  # 'A','B','C','D'
                        "text": o.text,
                        "position": o.position
                    }
                    for o in opts
                ],
            })

        return jsonify(out), 200


@api_blueprint.route("/question/add", methods=["POST"])
@require_jwt
def question_add():
    """
    Crea una nuova domanda globale con le sue opzioni.

    Payload atteso:
    {
      "text": "When do you prefer to take care of your plants?",
      "type": "preference",
      "active": true,              // opzionale, default True
      "options": [                 // opzionale ma consigliato
        "Weekdays only",
        "Weekends only",
        "Any day is fine",
        "Every other day"
      ]
    }
    """
    payload = _parse_json_body()

    text = (payload.get("text") or "").strip()
    qtype = (payload.get("type") or "").strip()
    active = payload.get("active", True)
    options = payload.get("options") or []

    if not text or not qtype:
        return jsonify({"error": "Campi obbligatori: text, type"}), 400

    if not isinstance(options, list) or not options:
        return jsonify({"error": "options deve essere una lista non vuota"}), 400

    with _session_ctx() as s:
        # crea la domanda
        q = Question(
            text=text,
            type=qtype,
            active=bool(active),
        )
        s.add(q)
        s.flush()  # per avere q.id

        # crea le opzioni
        for idx, opt_text in enumerate(options, start=1):
            label = chr(ord("A") + (idx - 1))  # 'A','B','C','D', ...
            opt = QuestionOption(
                question_id=q.id,
                label=label,
                text=str(opt_text),
                is_correct=False,
                position=idx,
            )
            s.add(opt)

        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        # se vuoi, potresti loggare anche le QuestionOption su un canale separato

        return jsonify({"ok": True, "id": str(q.id)}), 201


@api_blueprint.route("/question/update/<qid>", methods=["PATCH", "PUT"])
@require_jwt
def question_update(qid: str):
    """
    Aggiorna i campi base di una domanda (text, type, active).
    Per le opzioni servirebbe un endpoint dedicato (non gestito qui).
    """
    _ensure_uuid(qid, "question_id")
    payload = _parse_json_body()

    with _session_ctx() as s:
        q = s.get(Question, qid)
        if not q:
            return jsonify({"error": "Question not found"}), 404

        # consentiamo solo text, type, active
        if "text" in payload:
            q.text = (payload["text"] or "").strip()
        if "type" in payload:
            q.type = (payload["type"] or "").strip()
        if "active" in payload:
            q.active = bool(payload["active"])

        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        return jsonify({"ok": True, "id": str(q.id)}), 200


@api_blueprint.route("/question/delete/<qid>", methods=["DELETE"])
@require_jwt
def question_delete(qid: str):
    """
    Elimina una domanda globale.
    Le QuestionOption e UserQuestionAnswer collegate
    vengono eliminate in cascata (ON DELETE CASCADE).
    """
    _ensure_uuid(qid, "question_id")
    with _session_ctx() as s:
        q = s.get(Question, qid)
        if q:
            s.delete(q)
            _commit_or_409(s)
            write_changes_delete("question", qid)
        # 204 anche se la domanda non esiste (idempotente)
        return ("", 204)


# ========= Questionnaire (per utente loggato) =========

@api_blueprint.route("/questionnaire/questions", methods=["GET"])
@require_jwt
def questionnaire_get_questions():
    """
    Restituisce le domande del questionario per l'utente loggato,
    con opzioni ed eventuale risposta già data.

    È un semplice wrapper su repo.get_questions_for_user(user_id).
    """
    user_id = g.user_id

    try:
        questions = repo.get_questions_for_user(user_id)
        return jsonify(questions), 200
    except Exception as e:
        current_app.logger.exception(
            f"Error fetching questionnaire for user {user_id}: {e}"
        )
        return jsonify({"error": "Database error"}), 500


@api_blueprint.route("/questionnaire/answers", methods=["POST"])
@require_jwt
def questionnaire_submit_answers():
    """
    Salva le risposte dell'utente loggato al questionario.

    Payload atteso:
    {
      "answers": {
        "<question_id>": "1",   // indice opzione 1..4
        "<question_id>": "3",
        ...
      }
    }
    """
    user_id = g.user_id
    payload = _parse_json_body()
    answers = payload.get("answers")

    if not isinstance(answers, dict) or not answers:
        return jsonify({"error": "answers must be a non-empty object"}), 400

    try:
        repo.save_question_answers(user_id, answers)
        return jsonify({"ok": True}), 200

    except ValueError as e:
        # errore di validazione (ID domanda non valido, indice fuori range, ecc.)
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        current_app.logger.exception(
            f"Error saving questionnaire answers for user {user_id}: {e}"
        )
        return jsonify({"error": "Database error"}), 500


# ========= Reminder =========

# ========= Watering – OVERVIEW SETTIMANALE =========
@api_blueprint.route("/watering/overview", methods=["GET"])
@require_jwt
def watering_overview():
    """
    Restituisce una settimana (lun→dom).
    Una pianta compare SOLO NEI GIORNI CORRETTI:
      - giorno di next_due_at
      - oppure giorno dei log (done_at)
    """
    try:
        user_id = g.user_id
    except Exception:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())
        days = [(week_start + timedelta(days=i)) for i in range(7)]

        # ----------------------------------------
        # 1) Otteniamo tutte le piante con info
        # ----------------------------------------
        plants = repo.get_watering_overview_for_user(user_id)

        # ----------------------------------------
        # 2) Otteniamo tutti i log della settimana
        # ----------------------------------------
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        week_end_dt = week_start_dt + timedelta(days=7)

        with SessionLocal() as s:
            logs = (
                s.query(WateringLog)
                .filter(
                    WateringLog.user_id == user_id,
                    WateringLog.done_at >= week_start_dt,
                    WateringLog.done_at < week_end_dt,
                )
                .all()
            )

        # Raggruppiamo log per giorno e plant_id
        logs_by_day = {}
        for d in days:
            logs_by_day[d.isoformat()] = {}

        for log in logs:
            day_key = log.done_at.date().isoformat()
            pid = str(log.plant_id)
            logs_by_day[day_key].setdefault(pid, [])
            logs_by_day[day_key][pid].append({
                "done_at": log.done_at.isoformat(),
                "amount_ml": log.amount_ml,
                "note": log.note,
            })

        # ----------------------------------------
        # 3) Costruiamo settimana → solo giorni corretti
        # ----------------------------------------
        result = []

        for d in days:
            day_key = d.isoformat()
            plants_today = []

            for p in plants:
                pid = p["plant_id"]

                appears = False

                # A) next_due_at coincide con il giorno
                next_due = p.get("next_due_at")
                if next_due and next_due[:10] == day_key:
                    appears = True

                # B) esiste un log per quel giorno
                if pid in logs_by_day.get(day_key, {}):
                    appears = True

                if appears:
                    plants_today.append({
                        **p,
                        "logs_today": logs_by_day[day_key].get(pid, [])
                    })

            result.append({
                "date": day_key,
                "plants_count": len(plants_today),
                "plants": plants_today,
            })

        return jsonify(result), 200

    except Exception as e:
        print("[ERROR] /watering/overview:", e)
        return jsonify({"error": str(e)}), 500


# ========= Watering – L'UTENTE HA INNAFFIATO =========
@api_blueprint.route("/plant/<plant_id>/watering/do", methods=["POST"])
@require_jwt
def plant_do_watering(plant_id: str):
    print(f"[WATERING][DO] Called for plant_id={plant_id}")

    _ensure_uuid(plant_id, "plant_id")

    payload = _parse_json_body() or {}
    print(f"[WATERING][DO] Payload received: {payload}")

    # amount_ml obbligatorio
    amount_ml = payload.get("amount_ml")
    if amount_ml is None:
        print("[WATERING][DO] Missing amount_ml.")
        return jsonify({"error": "Campo obbligatorio: amount_ml"}), 400

    try:
        amount_ml = int(amount_ml)
    except (TypeError, ValueError):
        print("[WATERING][DO] amount_ml is not an integer.")
        return jsonify({"error": "amount_ml deve essere un intero"}), 400

    note = payload.get("note") or None
    done_at_raw = payload.get("done_at")
    done_at = None

    if done_at_raw:
        print(f"[WATERING][DO] Parsing done_at: {done_at_raw}")
        if isinstance(done_at_raw, str):
            try:
                done_at = datetime.fromisoformat(done_at_raw)
            except Exception:
                print("[WATERING][DO] Invalid ISO format for done_at.")
                return jsonify({"error": "done_at deve essere in formato ISO 8601"}), 400

    # Verifica che l'utente possieda la pianta
    with _session_ctx() as s:
        if not s.get(UserPlant, (g.user_id, plant_id)):
            print(f"[WATERING][DO] Forbidden: user {g.user_id} does not own plant {plant_id}.")
            return jsonify({"error": "Forbidden: non possiedi questa pianta"}), 403

    print(f"[WATERING][DO] Registering watering for user={g.user_id}, plant={plant_id}")

    res = reminder_service.register_watering_and_schedule_next(
        user_id=str(g.user_id),
        plant_id=plant_id,
        amount_ml=amount_ml,
        note=note,
        done_at=done_at,
    )

    if not res.get("ok"):
        print(f"[WATERING][DO] Error from service: {res}")
        return jsonify({"error": res.get("error", "Unable to register watering")}), 400

    print(f"[WATERING][DO] Watering registered successfully: {res}")

    return jsonify(
        {
            "ok": True,
            "plan_id": res.get("plan_id"),
            "plant_id": res.get("plant_id"),
            "last_watered_at": res.get("last_watered_at"),
            "next_due_at": res.get("next_due_at"),
            "interval_days": res.get("interval_days"),
        }
    ), 200


@api_blueprint.route("/plant/<plant_id>/watering/undo", methods=["POST"])
@require_jwt
def plant_undo_watering(plant_id):
    user_id = str(g.user_id)
    print(f"[UNDO][PLANT] plant_id={plant_id}, user_id={user_id}")

    with _session_ctx() as s:

        now = datetime.utcnow()
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_midnight = today_midnight + timedelta(days=1)

        print(f"[UNDO] Today range: {today_midnight} → {tomorrow_midnight}")

        # ---------------------------------------------------
        # 1) Trova SOLO il log REALE di oggi (ora ≠ 00:00)
        # ---------------------------------------------------
        real_log = (
            s.query(WateringLog)
            .filter(
                WateringLog.user_id == user_id,
                WateringLog.plant_id == plant_id,
                WateringLog.done_at >= today_midnight,
                WateringLog.done_at < tomorrow_midnight,
                WateringLog.done_at != today_midnight
            )
            .first()
        )

        if not real_log:
            print("[UNDO] No REAL log to undo.")
            return jsonify({"error": "Nessun watering da annullare"}), 400

        print(f"[UNDO] Removing REAL log: {real_log.done_at}")
        s.delete(real_log)

        # ---------------------------------------------------
        # 2) Cancella TUTTI i log FUTURI della pianta
        # ---------------------------------------------------
        future_logs = (
            s.query(WateringLog)
            .filter(
                WateringLog.user_id == user_id,
                WateringLog.plant_id == plant_id,
                WateringLog.done_at >= tomorrow_midnight
            )
            .all()
        )

        for fl in future_logs:
            print(f"[UNDO] Removing FUTURE log: {fl.done_at}")
            s.delete(fl)

        # ---------------------------------------------------
        # 3) Recupera piano
        # ---------------------------------------------------
        plan = (
            s.query(WateringPlan)
            .filter(
                WateringPlan.user_id == user_id,
                WateringPlan.plant_id == plant_id
            )
            .first()
        )

        if not plan:
            print("[UNDO] No plan found.")
            s.rollback()
            return jsonify({"error": "Nessun piano trovato"}), 400

        interval_days = int(plan.interval_days or 3)

        # ---------------------------------------------------
        # 4) Calcolo ml per log programmato
        # ---------------------------------------------------
        plant_obj = s.query(Plant).filter(Plant.id == plant_id).one_or_none()
        scheduled_ml = 150  # fallback base

        if plant_obj is not None:
            ml = 150
            wl = int(plant_obj.water_level or 3)
            if wl <= 2:
                ml = int(ml * 0.8)
            elif wl >= 4:
                ml = int(ml * 1.2)
            scheduled_ml = max(50, ml)

        # ---------------------------------------------------
        # 5) Ricrea log programmato a mezzanotte (00:00)
        # ---------------------------------------------------
        print(f"[UNDO] Creating SCHEDULED log at midnight {today_midnight}")

        new_sched = WateringLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            plant_id=plant_id,
            done_at=today_midnight,
            amount_ml=scheduled_ml,
            note="SCHEDULED FROM PLAN (UNDO)",
        )
        s.add(new_sched)

        # ---------------------------------------------------
        # 6) next_due_at = oggi a mezzanotte
        # ---------------------------------------------------
        plan.next_due_at = today_midnight
        print(f"[UNDO] next_due_at reset to {today_midnight}")

        # ---------------------------------------------------
        # 7) Ricrea reminder
        # ---------------------------------------------------
        s.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.entity_type == "plant",
            Reminder.entity_id == plant_id
        ).delete()

        new_rem = Reminder(
            user_id=user_id,
            title="Water your plant",
            note=None,
            scheduled_at=today_midnight,
            done_at=None,
            recurrence_rrule=None,
            entity_type="plant",
            entity_id=plant_id,
        )
        s.add(new_rem)

        # ---------------------------------------------------
        # 8) Commit finale
        # ---------------------------------------------------
        s.commit()

        print("[UNDO] Completed successfully.")

        return jsonify({
            "ok": True,
            "new_next_due_at": today_midnight.isoformat()
        })


@api_blueprint.route("/watering_plan/calendar-export", methods=["GET"])
@require_jwt
def watering_plan_calendar_export():
    """
    Esporta tutti i watering plan dell'utente loggato
    in un formato comodo da usare come eventi calendario sul telefono.
    """
    user_id = g.user_id

    with _session_ctx() as s:
        # Join con Plant per avere il nome pianta
        rows = (
            s.query(WateringPlan, Plant)
            .join(Plant, Plant.id == WateringPlan.plant_id)
            .filter(WateringPlan.user_id == user_id)
            .order_by(WateringPlan.next_due_at.asc())
            .all()
        )

        events = []
        for wp, plant in rows:
            # titolo leggibile per il calendario
            title = f"Water {plant.common_name or plant.scientific_name}"

            events.append({
                "id": str(wp.id),
                "plant_id": str(plant.id),
                "plant_name": plant.common_name or plant.scientific_name,
                "title": title,

                # quando parte il promemoria
                "start": wp.next_due_at.isoformat(),  # es. 2025-11-23T09:00:00

                # ogni quanti giorni si ripete
                "interval_days": wp.interval_days,

                # se vuoi farla usare per note/event description
                "notes": wp.notes,
            })

        return jsonify(events), 200


@api_blueprint.route("/reminder/all", methods=["GET"])
@require_jwt
def reminder_all():
    with _session_ctx() as s:
        rows = s.query(Reminder).order_by(Reminder.scheduled_at.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/reminder/add", methods=["POST"])
@require_jwt
def reminder_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Reminder)

    required = ["title", "scheduled_at"]  # user_id rimosso
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400

    data["user_id"] = g.user_id
    with _session_ctx() as s:
        r = Reminder(**data)
        s.add(r)
        _commit_or_409(s)
        write_changes_upsert("reminder", [_serialize_instance(r)])
        return jsonify({"ok": True, "id": r.id}), 201


@api_blueprint.route("/reminder/update/<rid>", methods=["PATCH", "PUT"])
@require_jwt
def reminder_update(rid: str):
    _ensure_uuid(rid, "reminder_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        r = s.get(Reminder, rid)
        if not r: return jsonify({"error": "Reminder not found"}), 404
        for k, v in _filter_fields_for_model(payload, Reminder).items():
            setattr(r, k, v)
        _commit_or_409(s)
        write_changes_upsert("reminder", [_serialize_instance(r)])
        return jsonify({"ok": True, "id": r.id}), 200


@api_blueprint.route("/reminder/delete/<rid>", methods=["DELETE"])
@require_jwt
def reminder_delete(rid: str):
    _ensure_uuid(rid, "reminder_id")
    with _session_ctx() as s:
        r = s.get(Reminder, rid)
        if r:
            s.delete(r)
            _commit_or_409(s)
        write_changes_delete("reminder", rid)
        return ("", 204)


@api_blueprint.route("/plant/<plant_id>/reminders", methods=["GET"])
@require_jwt
def get_reminders_for_plant(plant_id: str):
    _ensure_uuid(plant_id, "plant_id")
    with _session_ctx() as s:
        reminders = (
            s.query(Reminder)
            .filter(
                Reminder.user_id == g.user_id,
                Reminder.entity_type == "plant",
                Reminder.entity_id == plant_id,
            )
            .order_by(Reminder.scheduled_at.asc())
            .all()
        )

        # anche se non ce ne sono, restituisci una lista vuota (200)
        return jsonify([_serialize_instance(r) for r in reminders]), 200


@api_blueprint.route("/reminders", methods=["GET"])
@require_jwt
def get_all_reminders():
    with _session_ctx() as s:
        reminders = (
            s.query(Reminder)
            .filter(Reminder.user_id == g.user_id)
            .order_by(Reminder.scheduled_at.asc())
            .all()
        )
        return jsonify([_serialize_instance(r) for r in reminders]), 200


# ========= Upload Plant Photo =========
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}


@api_blueprint.route("/upload/plant-photo", methods=["POST"])
@require_jwt
def upload_plant_photo():
    """
    multipart/form-data:
      - file (required)
      - plant_id (required)
      - caption (optional)
    Returns: { ok: true, photo_id, url }
    """
    f = request.files.get("file")
    plant_id = request.form.get("plant_id")
    caption = request.form.get("caption")

    if not f or not f.filename:
        return jsonify({"error": "file missing"}), 400
    if not plant_id:
        return jsonify({"error": "plant_id missing"}), 400

    _, ext = os.path.splitext(secure_filename(f.filename))
    ext = ext.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Extension not allowed: {ext}"}), 400

    # Save the file in /app/uploads/plant/<plant_id>/<uuid>.ext
    dest_dir = os.path.join(current_app.config["UPLOAD_DIR"], "plant", plant_id)
    os.makedirs(dest_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(dest_dir, fname)
    f.save(dest_path)

    url = f"/uploads/plant/{plant_id}/{fname}"

    with _session_ctx() as s:
        plant = s.get(Plant, plant_id)
        if not plant:
            return jsonify({"error": "Plant not found"}), 404

        photo = PlantPhoto(plant_id=plant_id, url=url, caption=caption, order_index=0)
        s.add(photo)
        _commit_or_409(s)

        write_changes_upsert("plant_photo", [_serialize_instance(photo)])
        return jsonify({"ok": True, "photo_id": photo.id, "url": url}), 201


@api_blueprint.route("/plant/<pid>/photo", methods=["GET"])
def plant_main_photo(pid: str):
    """
    Returns the 'main photo' of the plant (first by order_index, then the most recent).
    404 if plant or photo not present.
    """
    with _session_ctx() as s:
        p = s.get(Plant, pid)
        if not p:
            return jsonify({"error": "Plant not found"}), 404

        photo = (
            s.query(PlantPhoto)
            .filter(PlantPhoto.plant_id == pid)
            .order_by(PlantPhoto.order_index.asc(), PlantPhoto.created_at.desc())
            .first()
        )
        if not photo:
            return jsonify({"error": "No photo for this plant"}), 404

        return jsonify(_serialize_instance(photo)), 200


@api_blueprint.route("/plant/<pid>/photos", methods=["GET"])
def plant_photos(pid: str):
    """
    Lists all photos of the plant ordered by order_index, then created_at desc.
    Query param: ?limit=K to limit the number.
    """
    limit = request.args.get("limit", type=int)
    with _session_ctx() as s:
        q = (
            s.query(PlantPhoto)
            .filter(PlantPhoto.plant_id == pid)
            .order_by(PlantPhoto.order_index.asc(), PlantPhoto.created_at.desc())
        )
        rows = q.limit(limit).all() if limit else q.all()
        return jsonify([_serialize_instance(r) for r in rows]), 200
