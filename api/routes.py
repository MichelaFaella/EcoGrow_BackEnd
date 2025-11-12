from __future__ import annotations

# Standard library
import os
import uuid
from contextlib import contextmanager
from datetime import datetime

# Third-party
from flask import Blueprint, jsonify, current_app, request, abort, g
from werkzeug.utils import secure_filename
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

# Local application
from services.repository_service import RepositoryService
from utils.jwt_helper import generate_token, validate_token
from models.entities import SizeEnum
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

# image_service = ImageProcessingService()
# reminder_service = ReminderService()
# disease_service = DiseaseRecognitionService()

@api_blueprint.errorhandler(401)
def auth_missing(e):
    return jsonify({"error": "Missing or invalid JWT token"}), 401


# ======== AUTH =========
@api_blueprint.route("/auth/login", methods=["POST"])
def auth_login():
    """
    JSON body: { "email": "...", "password": "..." }
    Returns:   { "access_token": "...", "user_id": "..." }
    + sets an HttpOnly 'refresh_token' cookie (persistent)
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email/password missing"}), 400

    with _session_ctx() as s:
        u = s.query(User).filter(func.lower(User.email) == email).first()
        if not u or not check_password_hash(u.password_hash, password):
            return jsonify({"error": "Invalid credentials"}), 401

        # 1) Access JWT (short-lived, handled by jwt_helper)
        access_token = generate_token(str(u.id))

        # 2) Refresh token stored in DB  with sliding expiry
        raw_refresh = secrets.token_urlsafe(48)
        rt = RefreshToken(
            user_id=str(u.id),
            token=raw_refresh,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TTL_DAYS),
        )
        s.add(rt)
        _commit_or_409(s)

        # 3) Response + HttpOnly cookie
        resp = jsonify({"access_token": access_token, "user_id": str(u.id)})
        resp.set_cookie(
            "refresh_token",
            raw_refresh,
            max_age=60 * 60 * 24 * REFRESH_TTL_DAYS,
            httponly=True,
            secure=False,      # True in production (HTTPS)
            samesite="Lax",
            path="/",          # backend reads the cookie on /auth/refresh and /auth/logout
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
            secure=False,      # True in produzione (HTTPS)
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
    # Don't use force=True: if Content-Type is not JSON -> standard 400
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        abort(400, description="Invalid JSON body")
    return data


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
        # add any FK here, e.g. "family_id": getattr(p, "family_id", None),
    }


# ========= Auth check =========
@api_blueprint.route("/check-auth", methods=["GET"])
def check_auth():
    tok = _extract_token()
    user_id = validate_token(tok) if tok else None
    if not user_id:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user_id": user_id}), 200


# ========= Ping =========
@api_blueprint.route("/ping", methods=["GET"])
def ping():
    return jsonify(ping="pong")


@api_blueprint.route("/families", methods=["GET"])
def get_families():
    try:
        families = repo.get_all_families()
        return jsonify(families), 200
    except Exception:
        return jsonify({"error": "Database error"}), 500


# ========= Plants (by user) =========
@api_blueprint.route("/plants", methods=["GET"])
def get_plants():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user identifier"}), 400
    try:
        plants = repo.get_plants_by_user(user_id)
        return jsonify(plants), 200
    except Exception:
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


# ========= CREATE Plant =========
@api_blueprint.route("/plant/add", methods=["POST"])
@require_jwt
def create_plant():
    payload = _parse_json_body()

    # --- id & timestamps (conserva il comportamento esistente) ---
    cols = _model_columns(Plant)
    if "id" in cols and "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    now = datetime.utcnow()
    if "created_at" in cols and "created_at" not in payload:
        payload["created_at"] = now
    if "updated_at" in cols:
        payload["updated_at"] = now

    if "size" in payload and payload["size"] is not None:
        size_val = str(payload["size"])
        allowed_sizes = {e.value for e in SizeEnum}
        if size_val not in allowed_sizes:
            return jsonify({"error": f"size must be one of {sorted(allowed_sizes)}"}), 400
        payload["size"] = SizeEnum(size_val)

    try:
        wl = int(payload.get("water_level"))
        ll = int(payload.get("light_level"))
        if not (1 <= wl <= 5) or not (1 <= ll <= 5):
            return jsonify({"error": "water_level/light_level must be in [1..5]"}), 400
    except Exception:
        return jsonify({"error": "water_level/light_level must be integer"}), 400

    try:
        tmin = int(payload.get("min_temp_c"))
        tmax = int(payload.get("max_temp_c"))
        if tmin >= tmax:
            return jsonify({"error": "min_temp_c must be < max_temp_c"}), 400
    except Exception:
        return jsonify({"error": "min_temp_c/max_temp_c must be integer"}), 400

    data = _filter_fields_for_model(payload, Plant)

    with _session_ctx() as s:
        try:
            # 1) Se il client passa family_id, usalo (con validazione)
            fam_id = (payload.get("family_id") or "").strip()
            if fam_id:
                _ensure_uuid(fam_id, "family_id")
                if not s.get(Family, fam_id):
                    return jsonify({"error": "Family not found"}), 400
                data["family_id"] = fam_id
            else:
                # 2) Fallback: deduci family dal scientific_name (comportamento esistente)
                fam_id = repo.get_family(data["scientific_name"])
                if not fam_id:
                    return jsonify({"error": "Family not found"}), 400
                data["family_id"] = fam_id

            # 3) Crea la pianta
            p = Plant(**data)
            s.add(p)
            _commit_or_409(s)
            write_changes_upsert("plant", [_serialize_instance(p)])

            # 4) (Facoltativo) collega all'utente se payload include metadati user_plant
            nickname = (payload.get("nickname") or "").strip() or None
            location_note = (payload.get("location_note") or "").strip() or None
            since_value = payload.get("since") or None  # YYYY-MM-DD o ISO

            if any([nickname, location_note, since_value]) and not s.get(UserPlant, (g.user_id, p.id)):
                up = UserPlant(
                    user_id=g.user_id,
                    plant_id=p.id,
                    nickname=nickname,
                    location_note=location_note,
                    since=since_value,
                )
                s.add(up)
                _commit_or_409(s)
                write_changes_upsert("user_plant", [_serialize_instance(up)])

            return jsonify({"ok": True, "id": str(p.id)}), 201

        except IntegrityError as e:
            s.rollback()
            return jsonify({"error": f"Conflict: {e.orig}"}), 409
        except DataError as e:
            s.rollback()
            return jsonify({"error": f"Bad data: {e.orig}"}), 400
        except Exception as e:
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

        # try to delete the file on disk if we know the URL
        if pp and pp.url and pp.url.startswith("/uploads/"):
            try:
                rel = pp.url[len("/uploads/"):]  # e.g. "plant/<pid>/<uuid>.png"
                base = os.path.realpath(current_app.config["UPLOAD_DIR"])
                full = os.path.realpath(os.path.join(base, rel))  # absolute path
                # safety: delete only inside UPLOAD_DIR
                if full.startswith(base) and os.path.exists(full):
                    os.remove(full)
                    # optional: remove dir if empty
                    dirpath = os.path.dirname(full)
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
            except Exception as e:
                current_app.logger.warning(f"Unable to remove file for photo_id={photo_id}: {e}")

        # delete the row from the DB
        if pp:
            s.delete(pp)
            _commit_or_409(s)

    # update changes.json (idempotent as you do with family_delete)
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

        # GENERATE JWT
        token = generate_token(u.id)

        return jsonify({
            "ok": True,
            "id": u.id,
            "token": token  # <--- JWT returned to client
        }), 201


@api_blueprint.route("/user/update/<uid>", methods=["PATCH", "PUT"])
@require_jwt
def user_update(uid: str):
    _ensure_uuid(uid, "user_id")
    payload = _parse_json_body()
    if payload.get("password"):
        payload["password_hash"] = generate_password_hash(payload.pop("password"))
    with _session_ctx() as s:
        u = s.get(User, uid)
        if not u: return jsonify({"error": "User not found"}), 404
        for k, v in _filter_fields_for_model(payload, User).items():
            setattr(u, k, v)
        u.updated_at = datetime.utcnow()
        _commit_or_409(s)
        write_changes_upsert("user", [_serialize_instance(u)])
        return jsonify({"ok": True, "id": u.id}), 200


@api_blueprint.route("/user/delete/<uid>", methods=["DELETE"])
@require_jwt
def user_delete(uid: str):
    _ensure_uuid(uid, "user_id")
    with _session_ctx() as s:
        u = s.get(User, uid)
        if u:
            s.delete(u)
            _commit_or_409(s)
        write_changes_delete("user", uid)
        return ("", 204)


# ========= UserPlant (composite PK: user_id + plant_id) =========
@api_blueprint.route("/user_plant/all", methods=["GET"])
@require_jwt
def user_plant_all():
    with _session_ctx() as s:
        rows = s.query(UserPlant).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


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
            nickname=payload.get("nickname"),
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


# ========= Friendship =========
@api_blueprint.route("/friendship/all", methods=["GET"])
@require_jwt
def friendship_all():
    with _session_ctx() as s:
        rows = s.query(Friendship).order_by(Friendship.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/friendship/add", methods=["POST"])
@require_jwt
def friendship_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Friendship)
    required = ["user_id_a", "user_id_b", "status"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Required fields: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        fr = Friendship(**data)
        s.add(fr)
        _commit_or_409(s)
        write_changes_upsert("friendship", [_serialize_instance(fr)])
        return jsonify({"ok": True, "id": fr.id}), 201


@api_blueprint.route("/friendship/update/<fid>", methods=["PATCH", "PUT"])
@require_jwt
def friendship_update(fid: str):
    _ensure_uuid(fid, "friendship_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        fr = s.get(Friendship, fid)
        if not fr: return jsonify({"error": "Friendship not found"}), 404
        for k, v in _filter_fields_for_model(payload, Friendship).items():
            setattr(fr, k, v)
        fr.updated_at = datetime.utcnow()
        _commit_or_409(s)
        write_changes_upsert("friendship", [_serialize_instance(fr)])
        return jsonify({"ok": True, "id": fr.id}), 200


@api_blueprint.route("/friendship/delete/<fid>", methods=["DELETE"])
@require_jwt
def friendship_delete(fid: str):
    _ensure_uuid(fid, "friendship_id")
    with _session_ctx() as s:
        fr = s.get(Friendship, fid)
        if fr:
            s.delete(fr)
            _commit_or_409(s)
        write_changes_delete("friendship", fid)
        return ("", 204)


# ========= SharedPlant =========
@api_blueprint.route("/shared_plant/all", methods=["GET"])
@require_jwt
def shared_plant_all():
    with _session_ctx() as s:
        rows = s.query(SharedPlant).order_by(SharedPlant.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/shared_plant/add", methods=["POST"])
@require_jwt
def shared_plant_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, SharedPlant)
    required = ["owner_user_id", "recipient_user_id", "plant_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Required fields: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        sp = SharedPlant(**data)
        s.add(sp)
        _commit_or_409(s)
        write_changes_upsert("shared_plant", [_serialize_instance(sp)])
        return jsonify({"ok": True, "id": sp.id}), 201


@api_blueprint.route("/shared_plant/update/<sid>", methods=["PATCH", "PUT"])
@require_jwt
def shared_plant_update(sid: str):
    _ensure_uuid(sid, "shared_plant_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        sp = s.get(SharedPlant, sid)
        if not sp: return jsonify({"error": "SharedPlant not found"}), 404
        for k, v in _filter_fields_for_model(payload, SharedPlant).items():
            setattr(sp, k, v)
        _commit_or_409(s)
        write_changes_upsert("shared_plant", [_serialize_instance(sp)])
        return jsonify({"ok": True, "id": sp.id}), 200


@api_blueprint.route("/shared_plant/delete/<sid>", methods=["DELETE"])
@require_jwt
def shared_plant_delete(sid: str):
    _ensure_uuid(sid, "shared_plant_id")
    with _session_ctx() as s:
        sp = s.get(SharedPlant, sid)
        if sp:
            s.delete(sp)
            _commit_or_409(s)
        write_changes_delete("shared_plant", sid)
        return ("", 204)


# ========= WateringPlan =========
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


# ========= Question =========
@api_blueprint.route("/question/all", methods=["GET"])
@require_jwt
def question_all():
    with _session_ctx() as s:
        # if Question has no created_at, order by id
        order_col = getattr(Question, "created_at", Question.id)
        rows = s.query(Question).order_by(order_col.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200


@api_blueprint.route("/question/add", methods=["POST"])
@require_jwt
def question_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Question)

    required = ["text", "type"]  # user_id rimosso
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400

    data["user_id"] = g.user_id
    with _session_ctx() as s:
        q = Question(**data)
        s.add(q)
        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        return jsonify({"ok": True, "id": q.id}), 201


@api_blueprint.route("/question/update/<qid>", methods=["PATCH", "PUT"])
@require_jwt
def question_update(qid: str):
    _ensure_uuid(qid, "question_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        q = s.get(Question, qid)
        if not q: return jsonify({"error": "Question not found"}), 404
        for k, v in _filter_fields_for_model(payload, Question).items():
            setattr(q, k, v)
        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        return jsonify({"ok": True, "id": q.id}), 200


@api_blueprint.route("/question/delete/<qid>", methods=["DELETE"])
@require_jwt
def question_delete(qid: str):
    _ensure_uuid(qid, "question_id")
    with _session_ctx() as s:
        q = s.get(Question, qid)
        if q:
            s.delete(q)
            _commit_or_409(s)
        write_changes_delete("question", qid)
        return ("", 204)


# ========= Reminder =========
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
