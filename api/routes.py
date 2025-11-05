from __future__ import annotations
import uuid
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import func
from models.entities import SizeEnum 

from flask import Blueprint, jsonify, request
from services.repository_service import RepositoryService
from services.image_processing_service import ImageProcessingService
from sqlalchemy.exc import IntegrityError, DataError
from flask import abort
# from services.reminder_service import ReminderService
# from services.disease_recognition_service import DiseaseRecognitionService

from utils.jwt_helper import validate_token
from models.entities import Disease, Family, Friendship, Plant, PlantDisease, PlantPhoto, Question, Reminder, SharedPlant, User, UserPlant, WateringLog, WateringPlan
api_blueprint = Blueprint("api", __name__)
repo = RepositoryService()
#image_service = ImageProcessingService()
# reminder_service = ReminderService()
# disease_service = DiseaseRecognitionService()

# Export/seed utilities
from models.scripts.replay_changes import seed_from_changes, write_changes_delete, write_changes_upsert
from models.base import SessionLocal
# ========= Helpers =========


def _model_columns(Model) -> set[str]:
    """Ritorna i nomi colonna SQLAlchemy del Model."""
    return {c.name for c in Model.__table__.columns}

def _filter_fields_for_model(payload: dict, Model, *, exclude: set[str] = None) -> dict:
    """Filtra il payload tenendo solo i campi che esistono nel Model."""
    cols = _model_columns(Model)
    if exclude:
        cols = cols - set(exclude)
    return {k: v for k, v in payload.items() if k in cols}

def _serialize_instance(instance) -> dict:
    """
    Serializza l'istanza su base colonne reali del modello:
    - converte UUID/DateTime in stringhe se necessario
    - include solo colonne effettive (niente attributi extra)
    """
    cols = _model_columns(type(instance))
    out = {}
    for c in cols:
        v = getattr(instance, c, None)
        # UUID → stringa (se serve)
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
    # Non usare force=True: se Content-Type non è JSON -> 400 standard
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
    """Serializza solo i campi persistenti che vuoi in changes.json."""
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
        # aggiungi qui eventuali FK, es. "family_id": getattr(p, "family_id", None),
    }


# ========= Auth check =========
@api_blueprint.route("/check-auth", methods=["GET"])
def check_auth():
    token = request.headers.get("Authorization")
    if not token or not validate_token(token):
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True}), 200


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
# ========= Plants (catalogo completo) =========
@api_blueprint.route("/plants/all", methods=["GET"])
def get_all_plants():
    try:
        plants = repo.get_all_plants_catalog()
        return jsonify(plants), 200
    except Exception:
        return jsonify({"error": "Database error"}), 500

# ========= CREATE Plant =========
@api_blueprint.route("/plant/add", methods=["POST"])
def create_plant():
    payload = _parse_json_body()

    cols = _model_columns(Plant)
    if "id" in cols and "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    now = datetime.utcnow()
    if "created_at" in cols and "created_at" not in payload:
        payload["created_at"] = now
    if "updated_at" in cols:
        payload["updated_at"] = now

    # --- size: opzionale; se presente validiamo e convertiamo a Enum ---
    if "size" in payload and payload["size"] is not None:
        size_val = str(payload["size"])
        if size_val not in ALLOWED_SIZES:
            return jsonify({"error": f"size deve essere in {sorted(ALLOWED_SIZES)}"}), 400
        payload["size"] = SizeEnum(size_val)

    data = _filter_fields_for_model(payload, Plant)

    required = ["scientific_name", "use", "water_level", "light_level",
                "min_temp_c", "max_temp_c", "category", "climate"]
    missing = [k for k in required if k not in data or data[k] in (None, "")]
    if missing:
        return jsonify({"error": f"Campi obbligatori mancanti: {', '.join(missing)}"}), 400

    try:
        wl = int(data["water_level"]); ll = int(data["light_level"])
        if not (1 <= wl <= 5): return jsonify({"error": "water_level deve essere tra 1 e 5"}), 400
        if not (1 <= ll <= 5): return jsonify({"error": "light_level deve essere tra 1 e 5"}), 400
    except Exception:
        return jsonify({"error": "water_level/light_level devono essere interi"}), 400

    try:
        tmin = int(data["min_temp_c"]); tmax = int(data["max_temp_c"])
        if not (tmin < tmax): return jsonify({"error": "min_temp_c deve essere < max_temp_c"}), 400
    except Exception:
        return jsonify({"error": "min_temp_c/max_temp_c devono essere interi"}), 400

    with _session_ctx() as s:
        try:
            p = Plant(**data)
            s.add(p)
            _commit_or_409(s)
            write_changes_upsert("plant", [_serialize_instance(p)])
            return jsonify({"ok": True, "id": str(getattr(p, "id", ""))}), 201
        except Exception as e:
            s.rollback()
            return jsonify({"error": f"DB error: {e}"}), 500

# ========= UPDATE Plant =========
@api_blueprint.route("/plant/update/<plant_id>", methods=["PATCH","PUT"])
def update_plant(plant_id: str):
    if not plant_id:
        return jsonify({"error": "plant_id mancante"}), 400
    _ensure_uuid(plant_id, "plant_id")
    payload = _parse_json_body()

    # --- size in update: se passato, valida e converti a Enum ---
    if "size" in payload and payload["size"] is not None:
        size_val = str(payload["size"])
        if size_val not in ALLOWED_SIZES:
            return jsonify({"error": f"size deve essere in {sorted(ALLOWED_SIZES)}"}), 400
        payload["size"] = SizeEnum(size_val)

    with _session_ctx() as s:
        p = s.get(Plant, plant_id)
        if p is None:
            return jsonify({"error": "Plant non trovata"}), 404

        allowed = [
            "scientific_name", "common_name", "use", "origin",
            "water_level", "light_level", "min_temp_c", "max_temp_c",
            "category", "climate", "pests", "family_id",
            "size",   # <--- aggiunto
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
        return jsonify({"error": "plant_id mancante"}), 400
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
def family_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Family)
    if not data.get("name"):
        return jsonify({"error": "Campo 'name' obbligatorio"}), 400
    with _session_ctx() as s:
        f = Family(**data); s.add(f)
        _commit_or_409(s)
        write_changes_upsert("family", [_serialize_instance(f)])
        return jsonify({"ok": True, "id": f.id}), 201

@api_blueprint.route("/family/update/<fid>", methods=["PATCH","PUT"])
def family_update(fid: str):
    _ensure_uuid(fid, "family_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        f = s.get(Family, fid)
        if not f: return jsonify({"error":"Family non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, Family).items():
            setattr(f,k,v)
        _commit_or_409(s)
        write_changes_upsert("family", [_serialize_instance(f)])
        return jsonify({"ok": True, "id": f.id}), 200

@api_blueprint.route("/family/delete/<fid>", methods=["DELETE"])
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
    Ritorna tutte le piante con la size indicata.
    size ∈ {piccolo, medio, grande, gigante}
    """
    if not size or size not in ALLOWED_SIZES:
        return jsonify({"error": f"size deve essere in {sorted(ALLOWED_SIZES)}"}), 400

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
    Ritorna tutte le piante con 'use' corrispondente (match case-insensitive).
    Esempi di use: 'ornamental', 'medicinal', ecc.
    """
    if not use:
        return jsonify({"error": "Parametro 'use' mancante"}), 400

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
def plant_photo_all():
    with _session_ctx() as s:
        rows = s.query(PlantPhoto).order_by(PlantPhoto.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/plant/photo/add/<plant_id>", methods=["POST"])
def plant_photo_add(plant_id: str):
    _ensure_uuid(plant_id, "plant_id")
    payload = _parse_json_body()
    data = _filter_fields_for_model({**payload, "plant_id": plant_id}, PlantPhoto)
    if not data.get("url"):
        return jsonify({"error":"url obbligatorio"}), 400
    with _session_ctx() as s:
        ph = PlantPhoto(**data); s.add(ph)
        _commit_or_409(s)
        write_changes_upsert("plant_photo", [_serialize_instance(ph)])
        return jsonify({"ok": True, "id": ph.id}), 201

@api_blueprint.route("/plant/photo/update/<photo_id>", methods=["PATCH","PUT"])
def plant_photo_update(photo_id: str):
    _ensure_uuid(photo_id, "photo_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        ph = s.get(PlantPhoto, photo_id)
        if not ph: return jsonify({"error":"PlantPhoto non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, PlantPhoto).items():
            setattr(ph,k,v)
        _commit_or_409(s)
        write_changes_upsert("plant_photo", [_serialize_instance(ph)])
        return jsonify({"ok": True, "id": ph.id}), 200

@api_blueprint.route("/plant/photo/delete/<photo_id>", methods=["DELETE"])
def plant_photo_delete(photo_id: str):
    _ensure_uuid(photo_id, "photo_id")
    with _session_ctx() as s:
        ph = s.get(PlantPhoto, photo_id)
        if ph:
            s.delete(ph)
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
def disease_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Disease)
    if not data.get("name") or not data.get("description"):
        return jsonify({"error":"name e description obbligatori"}), 400
    with _session_ctx() as s:
        d = Disease(**data); s.add(d)
        _commit_or_409(s)
        write_changes_upsert("disease", [_serialize_instance(d)])
        return jsonify({"ok": True, "id": d.id}), 201

@api_blueprint.route("/disease/update/<did>", methods=["PATCH","PUT"])
def disease_update(did: str):
    _ensure_uuid(did, "disease_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        d = s.get(Disease, did)
        if not d: return jsonify({"error":"Disease non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, Disease).items():
            setattr(d,k,v)
        _commit_or_409(s)
        write_changes_upsert("disease", [_serialize_instance(d)])
        return jsonify({"ok": True, "id": d.id}), 200

@api_blueprint.route("/disease/delete/<did>", methods=["DELETE"])
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
def plant_disease_all():
    with _session_ctx() as s:
        rows = s.query(PlantDisease).order_by(PlantDisease.detected_at.desc().nulls_last()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/plant_disease/add", methods=["POST"])
def plant_disease_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, PlantDisease)
    required = ["plant_id","disease_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        pd = PlantDisease(**data); s.add(pd)
        _commit_or_409(s)
        write_changes_upsert("plant_disease", [_serialize_instance(pd)])
        return jsonify({"ok": True, "id": pd.id}), 201

@api_blueprint.route("/plant_disease/update/<pdid>", methods=["PATCH","PUT"])
def plant_disease_update(pdid: str):
    _ensure_uuid(pdid, "plant_disease_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        pd = s.get(PlantDisease, pdid)
        if not pd: return jsonify({"error":"PlantDisease non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, PlantDisease).items():
            setattr(pd,k,v)
        _commit_or_409(s)
        write_changes_upsert("plant_disease", [_serialize_instance(pd)])
        return jsonify({"ok": True, "id": pd.id}), 200

@api_blueprint.route("/plant_disease/delete/<pdid>", methods=["DELETE"])
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
def user_all():
    with _session_ctx() as s:
        rows = s.query(User).order_by(User.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/user/add", methods=["POST"])
def user_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, User)
    required = ["email","password_hash","first_name","last_name"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        u = User(**data); s.add(u)
        _commit_or_409(s)
        write_changes_upsert("user", [_serialize_instance(u)])
        return jsonify({"ok": True, "id": u.id}), 201

@api_blueprint.route("/user/update/<uid>", methods=["PATCH","PUT"])
def user_update(uid: str):
    _ensure_uuid(uid, "user_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        u = s.get(User, uid)
        if not u: return jsonify({"error":"User non trovato"}), 404
        for k,v in _filter_fields_for_model(payload, User).items():
            setattr(u,k,v)
        u.updated_at = datetime.utcnow()
        _commit_or_409(s)
        write_changes_upsert("user", [_serialize_instance(u)])
        return jsonify({"ok": True, "id": u.id}), 200

@api_blueprint.route("/user/delete/<uid>", methods=["DELETE"])
def user_delete(uid: str):
    _ensure_uuid(uid, "user_id")
    with _session_ctx() as s:
        u = s.get(User, uid)
        if u:
            s.delete(u)
            _commit_or_409(s)
        write_changes_delete("user", uid)
        return ("", 204)

# ========= UserPlant (PK composta: user_id + plant_id) =========
@api_blueprint.route("/user_plant/all", methods=["GET"])
def user_plant_all():
    with _session_ctx() as s:
        rows = s.query(UserPlant).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/user_plant/add", methods=["POST"])
def user_plant_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, UserPlant)
    required = ["user_id","plant_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        up = UserPlant(**data); s.add(up)
        _commit_or_409(s)
        write_changes_upsert("user_plant", [_serialize_instance(up)])
        return jsonify({"ok": True}), 201

@api_blueprint.route("/user_plant/delete", methods=["DELETE"])
def user_plant_delete():
    user_id = request.args.get("user_id"); plant_id = request.args.get("plant_id")
    if not user_id or not plant_id:
        return jsonify({"error": "user_id e plant_id sono richiesti"}), 400
    _ensure_uuid(user_id, "user_id"); _ensure_uuid(plant_id, "plant_id")
    with _session_ctx() as s:
        row = s.get(UserPlant, (user_id, plant_id))
        if row:
            s.delete(row)
            _commit_or_409(s)
        write_changes_upsert("user_plant", [{"user_id": user_id, "plant_id": plant_id, "_delete": True}])
        return ("", 204)

# ========= Friendship =========
@api_blueprint.route("/friendship/all", methods=["GET"])
def friendship_all():
    with _session_ctx() as s:
        rows = s.query(Friendship).order_by(Friendship.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/friendship/add", methods=["POST"])
def friendship_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Friendship)
    required = ["user_id_a","user_id_b","status"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        fr = Friendship(**data); s.add(fr)
        _commit_or_409(s)
        write_changes_upsert("friendship", [_serialize_instance(fr)])
        return jsonify({"ok": True, "id": fr.id}), 201

@api_blueprint.route("/friendship/update/<fid>", methods=["PATCH","PUT"])
def friendship_update(fid: str):
    _ensure_uuid(fid, "friendship_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        fr = s.get(Friendship, fid)
        if not fr: return jsonify({"error":"Friendship non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, Friendship).items():
            setattr(fr,k,v)
        fr.updated_at = datetime.utcnow()
        _commit_or_409(s)
        write_changes_upsert("friendship", [_serialize_instance(fr)])
        return jsonify({"ok": True, "id": fr.id}), 200

@api_blueprint.route("/friendship/delete/<fid>", methods=["DELETE"])
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
def shared_plant_all():
    with _session_ctx() as s:
        rows = s.query(SharedPlant).order_by(SharedPlant.created_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/shared_plant/add", methods=["POST"])
def shared_plant_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, SharedPlant)
    required = ["owner_user_id","recipient_user_id","plant_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        sp = SharedPlant(**data); s.add(sp)
        _commit_or_409(s)
        write_changes_upsert("shared_plant", [_serialize_instance(sp)])
        return jsonify({"ok": True, "id": sp.id}), 201

@api_blueprint.route("/shared_plant/update/<sid>", methods=["PATCH","PUT"])
def shared_plant_update(sid: str):
    _ensure_uuid(sid, "shared_plant_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        sp = s.get(SharedPlant, sid)
        if not sp: return jsonify({"error":"SharedPlant non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, SharedPlant).items():
            setattr(sp,k,v)
        _commit_or_409(s)
        write_changes_upsert("shared_plant", [_serialize_instance(sp)])
        return jsonify({"ok": True, "id": sp.id}), 200

@api_blueprint.route("/shared_plant/delete/<sid>", methods=["DELETE"])
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
def watering_plan_all():
    with _session_ctx() as s:
        rows = s.query(WateringPlan).order_by(WateringPlan.next_due_at.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/watering_plan/add", methods=["POST"])
def watering_plan_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, WateringPlan)
    required = ["user_id","plant_id","next_due_at","interval_days"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        wp = WateringPlan(**data); s.add(wp)
        _commit_or_409(s)
        write_changes_upsert("watering_plan", [_serialize_instance(wp)])
        return jsonify({"ok": True, "id": wp.id}), 201

@api_blueprint.route("/watering_plan/update/<wid>", methods=["PATCH","PUT"])
def watering_plan_update(wid: str):
    _ensure_uuid(wid, "watering_plan_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        wp = s.get(WateringPlan, wid)
        if not wp: return jsonify({"error":"WateringPlan non trovato"}), 404
        for k,v in _filter_fields_for_model(payload, WateringPlan).items():
            setattr(wp,k,v)
        _commit_or_409(s)
        write_changes_upsert("watering_plan", [_serialize_instance(wp)])
        return jsonify({"ok": True, "id": wp.id}), 200

@api_blueprint.route("/watering_plan/delete/<wid>", methods=["DELETE"])
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
def watering_log_all():
    with _session_ctx() as s:
        rows = s.query(WateringLog).order_by(WateringLog.done_at.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/watering_log/add", methods=["POST"])
def watering_log_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, WateringLog)
    required = ["user_id","plant_id","done_at","amount_ml"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        wl = WateringLog(**data); s.add(wl)
        _commit_or_409(s)
        write_changes_upsert("watering_log", [_serialize_instance(wl)])
        return jsonify({"ok": True, "id": wl.id}), 201

@api_blueprint.route("/watering_log/update/<lid>", methods=["PATCH","PUT"])
def watering_log_update(lid: str):
    _ensure_uuid(lid, "watering_log_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        wl = s.get(WateringLog, lid)
        if not wl: return jsonify({"error":"WateringLog non trovato"}), 404
        for k,v in _filter_fields_for_model(payload, WateringLog).items():
            setattr(wl,k,v)
        _commit_or_409(s)
        write_changes_upsert("watering_log", [_serialize_instance(wl)])
        return jsonify({"ok": True, "id": wl.id}), 200

@api_blueprint.route("/watering_log/delete/<lid>", methods=["DELETE"])
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
def question_all():
    with _session_ctx() as s:
        # se non hai created_at su Question, ordino per id
        order_col = getattr(Question, "created_at", Question.id)
        rows = s.query(Question).order_by(order_col.desc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/question/add", methods=["POST"])
def question_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Question)
    required = ["user_id","text","type"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        q = Question(**data); s.add(q)
        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        return jsonify({"ok": True, "id": q.id}), 201

@api_blueprint.route("/question/update/<qid>", methods=["PATCH","PUT"])
def question_update(qid: str):
    _ensure_uuid(qid, "question_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        q = s.get(Question, qid)
        if not q: return jsonify({"error":"Question non trovata"}), 404
        for k,v in _filter_fields_for_model(payload, Question).items():
            setattr(q,k,v)
        _commit_or_409(s)
        write_changes_upsert("question", [_serialize_instance(q)])
        return jsonify({"ok": True, "id": q.id}), 200

@api_blueprint.route("/question/delete/<qid>", methods=["DELETE"])
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
def reminder_all():
    with _session_ctx() as s:
        rows = s.query(Reminder).order_by(Reminder.scheduled_at.asc()).all()
        return jsonify([_serialize_instance(r) for r in rows]), 200

@api_blueprint.route("/reminder/add", methods=["POST"])
def reminder_add():
    payload = _parse_json_body()
    data = _filter_fields_for_model(payload, Reminder)
    required = ["user_id","title","scheduled_at"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Campi obbligatori: {', '.join(missing)}"}), 400
    with _session_ctx() as s:
        r = Reminder(**data); s.add(r)
        _commit_or_409(s)
        write_changes_upsert("reminder", [_serialize_instance(r)])
        return jsonify({"ok": True, "id": r.id}), 201

@api_blueprint.route("/reminder/update/<rid>", methods=["PATCH","PUT"])
def reminder_update(rid: str):
    _ensure_uuid(rid, "reminder_id")
    payload = _parse_json_body()
    with _session_ctx() as s:
        r = s.get(Reminder, rid)
        if not r: return jsonify({"error":"Reminder non trovato"}), 404
        for k,v in _filter_fields_for_model(payload, Reminder).items():
            setattr(r,k,v)
        _commit_or_409(s)
        write_changes_upsert("reminder", [_serialize_instance(r)])
        return jsonify({"ok": True, "id": r.id}), 200

@api_blueprint.route("/reminder/delete/<rid>", methods=["DELETE"])
def reminder_delete(rid: str):
    _ensure_uuid(rid, "reminder_id")
    with _session_ctx() as s:
        r = s.get(Reminder, rid)
        if r:
            s.delete(r)
            _commit_or_409(s)
        write_changes_delete("reminder", rid)
        return ("", 204)
