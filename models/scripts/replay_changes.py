# models/scripts/replay_changes.py
from __future__ import annotations
import os, json, logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, date  
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert as mysql_insert

from models.base import SessionLocal
from models.entities import (
    Family, Plant, PlantPhoto,
    User, UserPlant,
    WateringPlan, WateringLog,
    Reminder, Question,
    Disease, PlantDisease,
    SharedPlant, Friendship,
)

logger = logging.getLogger(__name__)

# Mappa nome-tabella -> ORM class
TABLES = {
    "family": Family,
    "plant": Plant,
    "plant_photo": PlantPhoto,
    "user": User,
    "user_plant": UserPlant,
    "watering_plan": WateringPlan,
    "watering_log": WateringLog,
    "reminder": Reminder,
    "question": Question,
    "disease": Disease,
    "plant_disease": PlantDisease,
    "shared_plant": SharedPlant,
    "friendship": Friendship,
}

# Path del changes.json (env override) – default: ./models/scripts/fixtures/changes.json
DEFAULT_CHANGES = Path(__file__).parent / "fixtures" / "changes.json"
CHANGES_PATH = Path(os.getenv("CHANGES_PATH", str(DEFAULT_CHANGES)))


# -------------------------
# Utilities file JSON
# -------------------------
def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    # fallback per UUID/Decimal/oggetti vari
    try:
        return str(o)
    except Exception:
        return None   

def load_changes(path: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    p = Path(path)
    if not p.exists():
        logger.info(f"[seed] changes file not found: {p}")
        return {}
    raw = p.read_bytes()
    if not raw.strip():
        logger.info(f"[seed] changes file empty: {p}")
        return {}
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"[seed] invalid changes format (want object): {p}")
    # garantisci liste per ogni tabella
    for k, v in list(data.items()):
        if not isinstance(v, list):
            data[k] = []
    return data

def save_changes(path: str | Path, data: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Salva JSON su 'path'.
    - Prova atomico: write su .tmp + replace.
    - Fallback robusto (bind-mount): lock + truncate+write+fsync sul file target.
    """
    import io, json, os, errno
    from pathlib import Path

    p = Path(path)
    _ensure_parent(p)

    # ⬇️ unica modifica: aggiunto default=_json_default
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    # 1) Tentativo atomico classico
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)  # atomic move
        return
    except OSError as e:
        # Emblematico su bind-mount: [Errno 16] Device or resource busy
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        # continua con fallback
        if e.errno not in (errno.EBUSY, errno.EXDEV, errno.EPERM, errno.EACCES):
            # per altri errori, rilancia
            raise

    # 2) Fallback: scrittura in place con lock+fsync
    # Nota: fcntl è Linux-only (ok nel container)
    try:
        import fcntl
    except Exception:
        fcntl = None

    # apri in lettura/scrittura, crea se non esiste
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        with os.fdopen(fd, "r+", encoding="utf-8") as f:
            if fcntl:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass
            f.seek(0)
            f.truncate()
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
            if fcntl:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
    except Exception:
        # in caso di problemi residui, ultimo tentativo: scrivi su /tmp e poi copia bytes
        import shutil, tempfile
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(payload)
            tmp_path = tf.name
        try:
            with open(tmp_path, "rb") as src, open(p, "wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

# -------------------------
# Normalizzazioni
# -------------------------
def _coerce_datetimes_for_db(row: dict) -> dict:
    # converti stringhe ISO → datetime per colonne DATETIME
    for k in ("created_at", "updated_at", "ended_sharing_at", "answered_at", "scheduled_at", "done_at", "next_due_at", "detected_at"):
        v = row.get(k)
        if isinstance(v, str):
            try:
                row[k] = datetime.fromisoformat(v.replace("Z", ""))
            except Exception:
                # se non interpretabile, lasciala fuori: verrà messo default ORM/DB
                row.pop(k, None)
    return row

def _normalize_for_file(table: str, row: dict) -> dict:
    # Se mancano created_at/updated_at e la tabella li usa, aggiungili come ISO string
    needs_created = table in {"plant", "user", "reminder", "plant_photo"}
    needs_updated = table in {"plant", "user"}
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    out = dict(row)
    if needs_created and "created_at" not in out:
        out["created_at"] = now_iso
    if needs_updated and "updated_at" not in out:
        out["updated_at"] = now_iso
    return out


# -------------------------
# DB helpers
# -------------------------
def _upsert_db(session: Session, model, row: dict) -> None:
    table = model.__table__
    stmt = mysql_insert(table).values(**row)
    update_cols = {c.name: stmt.inserted[c.name] for c in table.columns if not c.primary_key}
    if "updated_at" in update_cols:
        update_cols["updated_at"] = datetime.utcnow()
    stmt = stmt.on_duplicate_key_update(**update_cols)
    session.execute(stmt)

def _delete_db(session: Session, model, row: dict) -> int:
    # supponiamo PK singola 'id'
    pk_cols = [c for c in model.__table__.columns if c.primary_key]
    if not pk_cols:
        return 0
    _id = row.get("id")
    if not _id:
        return 0
    return session.query(model).filter(pk_cols[0] == _id).delete()


# -------------------------
# API per le route
# -------------------------
def write_changes_upsert(table: str, rows: List[Dict[str, Any]], path: str | Path | None = None) -> int:
    """
    Aggiorna il file changes.json facendo upsert per chiave 'id' nella tabella indicata.
    Se un row non ha 'id', viene aggiunto così com'è (non deduplicabile).
    Ritorna quante righe sono state scritte/aggiornate.
    """
    p = Path(path) if path is not None else CHANGES_PATH
    data = load_changes(p)

    existing: List[Dict[str, Any]] = data.get(table, [])
    index_by_id = {r.get("id"): i for i, r in enumerate(existing) if isinstance(r, dict) and r.get("id")}

    applied = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        r = _normalize_for_file(table, r)
        rid = r.get("id")
        if rid and rid in index_by_id:
            existing[index_by_id[rid]] = r
        else:
            existing.append(r)
            if rid:
                index_by_id[rid] = len(existing) - 1
        applied += 1

    data[table] = existing
    save_changes(p, data)
    logger.info(f"[changes] upsert file {p} table={table} applied={applied}")
    return applied


def write_changes_delete(table: str, id_value: str, path: str | Path | None = None) -> int:
    """
    Appende/aggiorna nel file una riga {id: ..., _delete: true} per la tabella indicata.
    """
    if not id_value:
        return 0
    return write_changes_upsert(table, [{"id": id_value, "_delete": True}], path=path)


def seed_from_changes(path: str | Path | None = None) -> int:
    """
    Applica le modifiche in changes.json in modo idempotente.
    - upsert per righe normali
    - delete se {_delete: true}
    Ritorna il numero di operazioni DB applicate.
    """
    p = Path(path) if path is not None else CHANGES_PATH
    changes = load_changes(p)
    if not changes:
        return 0

    total = 0
    with SessionLocal() as session:
        for table_name, entries in changes.items():
            model = TABLES.get(table_name)
            if model is None or not isinstance(entries, list):
                continue

            applied_here = 0
            for row in entries:
                if not isinstance(row, dict):
                    continue

                if row.get("_delete") is True:
                    applied_here += _delete_db(session, model, row)
                    continue

                row_db = _coerce_datetimes_for_db(dict(row))
                _upsert_db(session, model, row_db)
                applied_here += 1

            total += applied_here
            logger.info(f"[seed] {table_name}: applied {applied_here}")

        session.commit()

    logger.info(f"[seed] total applied: {total} from {p}")
    return total
