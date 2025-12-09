# models/scripts/replay_changes.py
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.base import SessionLocal
from models.entities import (
    Family,
    Plant,
    PlantPhoto,
    User,
    UserPlant,
    WateringPlan,
    WateringLog,
    Reminder,
    Question,
    Disease,
    PlantDisease,
    SharedPlant,
    Friendship,
)

logger = logging.getLogger(__name__)

# Mappa nome tabella -> modello ORM
TABLES: Dict[str, Any] = {
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

# Ordine logico di seed per rispettare le FK
SEED_ORDER: List[str] = [
    "family",
    "plant",
    "plant_photo",
    "user",
    "disease",
    "plant_disease",
    "watering_plan",
    "user_plant",
    "watering_log",
    "shared_plant",
    "friendship",
    "reminder",
    "question",
]

# Chiavi che tendenzialmente rappresentano DATETIME sul DB
_DATETIME_KEYS = {
    "created_at",
    "updated_at",
    "ended_sharing_at",
    "scheduled_at",
    "done_at",
    "next_due_at",
    "detected_at",
    "last_used_at",
    "expires_at",
}

# Chiavi che tendenzialmente rappresentano DATE sul DB
_DATE_KEYS = {
    "since",
}


# ---------------------------------------------------------------------------
# Utility JSON / path
# ---------------------------------------------------------------------------

def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _stable_disease_id(name: str) -> str:
    """
    UUID deterministico basato sul nome (o stable_key) della malattia.
    Così non creiamo nuovi id ad ogni riavvio.
    """
    base = f"ecogrow-disease::{name.strip().lower()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, base))


def _json_default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    try:
        return str(o)
    except Exception:
        return None


def load_changes(path: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    Carica il changes.json. Se non esiste o è vuoto, restituisce {}.
    Garantisce che ogni valore sia una lista.
    """
    p = Path(path)
    if not p.exists():
        logger.info(f"[seed] changes file not found: {p}")
        return {}

    raw = p.read_bytes()
    if not raw.strip():
        logger.info(f"[seed] changes file empty: {p}")
        return {}

    # Rimuovi eventuale BOM
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
    import json, os, errno
    from pathlib import Path

    p = Path(path)
    _ensure_parent(p)

    payload = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    # 1) Tentativo atomico classico
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)  # atomic move
        return
    except OSError as e:
        # Tipico su bind-mount di singolo file: [Errno 16] Device or resource busy
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        # Se NON è uno degli errori “attesi”, rilanciamo
        if e.errno not in (errno.EBUSY, errno.EXDEV, errno.EPERM, errno.EACCES):
            raise
        # altrimenti continuiamo col fallback

    # 2) Fallback: scrittura in place con lock+fsync
    try:
        try:
            import fcntl  # Linux only, ok in Docker
        except Exception:
            fcntl = None

        fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            with os.fdopen(fd, "r+", encoding="utf-8") as f:
                if fcntl is not None:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except Exception:
                        pass

                f.seek(0)
                f.truncate()
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

                if fcntl is not None:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
        except Exception:
            # 3) Ultimo fallback: scrivo su /tmp e poi copio i bytes
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
    except Exception:
        # Se proprio qui va tutto male, allora sì: facciamo emergere l'errore
        raise


# ---------------------------------------------------------------------------
# Normalizzazioni
# ---------------------------------------------------------------------------

def _coerce_datetimes_for_db(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte stringhe ISO (quando possibile) in datetime/date per certe chiavi note.
    Se il parse fallisce, lascia il valore invariato (il DB/ORM gestirà).
    """
    out = dict(row)

    for k in _DATETIME_KEYS:
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = datetime.fromisoformat(v.replace("Z", ""))
            except Exception:
                # lascio la stringa così com'è (MySQL sa gestire alcune stringhe ISO)
                pass

    for k in _DATE_KEYS:
        v = out.get(k)
        if isinstance(v, str) and len(v) == 10:
            # forma tipica 'YYYY-MM-DD'
            try:
                out[k] = date.fromisoformat(v)
            except Exception:
                pass

    return out


def _normalize_for_file(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizza una riga PRIMA di scriverla su changes.json.
    In particolare aggiunge created_at/updated_at per alcune tabelle se mancanti.
    """
    needs_created = table in {"plant", "user", "reminder", "plant_photo"}
    needs_updated = table in {"plant", "user"}
    now_iso = datetime.utcnow().isoformat(timespec="seconds")

    out = dict(row)
    if needs_created and "created_at" not in out:
        out["created_at"] = now_iso
    if needs_updated and "updated_at" not in out:
        out["updated_at"] = now_iso
    return out


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert_db(session: Session, model: Any, row: Dict[str, Any]) -> None:
    """
    Esegue un INSERT ... ON DUPLICATE KEY UPDATE usando mysql_insert.
    - Salta le colonne primary key
    - Salta le colonne generated/computed (es. user_min/user_max in Friendship)
    """
    table = model.__table__
    stmt = mysql_insert(table).values(**row)

    update_cols: Dict[str, Any] = {}

    for c in table.columns:
        # niente PK nell'UPDATE
        if c.primary_key:
            continue
        # niente colonne generate (Computed) nell'UPDATE
        if getattr(c, "computed", None) is not None:
            continue

        update_cols[c.name] = stmt.inserted[c.name]

    # Se c'è updated_at, sovrascrivilo con l'UTC corrente
    if "updated_at" in update_cols:
        update_cols["updated_at"] = datetime.utcnow()

    stmt = stmt.on_duplicate_key_update(**update_cols)
    session.execute(stmt)

def _delete_db(session: Session, model: Any, row: Dict[str, Any]) -> int:
    """
    Cancella una riga in base a:
    - id (se presente), oppure
    - tutti i campi della primary key (se forniti).
    Ritorna il numero di righe cancellate.
    """
    pk_cols = list(model.__table__.primary_key.columns)

    # Caso semplice: se c'è id, usalo
    if "id" in row and row["id"]:
        return session.query(model).filter_by(id=row["id"]).delete()

    # Altrimenti prova a usare tutte le PK
    if pk_cols and all(col.name in row for col in pk_cols):
        filt = {col.name: row[col.name] for col in pk_cols}
        return session.query(model).filter_by(**filt).delete()

    logger.warning(
        "[seed] cannot build delete filter for table=%s from row=%s",
        model.__tablename__,
        row,
    )
    return 0


# ---------------------------------------------------------------------------
# API per le route / aggiornamento changes.json
# ---------------------------------------------------------------------------

def write_changes_upsert(
    table: str,
    rows: List[Dict[str, Any]],
    path: str | Path | None = None,
) -> int:
    """
    Aggiorna il file changes.json facendo upsert per chiave 'id' nella tabella indicata.
    Se una row non ha 'id', viene aggiunta così com'è (non deduplicabile).
    Ritorna quante righe sono state scritte/aggiornate.
    """
    p = Path(path) if path is not None else CHANGES_PATH
    data = load_changes(p)

    existing: List[Dict[str, Any]] = data.get(table, [])
    if not isinstance(existing, list):
        existing = []

    index_by_id: Dict[str, int] = {
        r.get("id"): i
        for i, r in enumerate(existing)
        if isinstance(r, dict) and r.get("id")
    }

    applied = 0
    for r in rows:
        if not isinstance(r, dict):
            continue

        r_norm = _normalize_for_file(table, r)
        rid = r_norm.get("id")

        if rid and rid in index_by_id:
            existing[index_by_id[rid]] = r_norm
        else:
            existing.append(r_norm)
            if rid:
                index_by_id[rid] = len(existing) - 1

        applied += 1

    data[table] = existing
    save_changes(p, data)
    logger.info(f"[changes] upsert file {p} table={table} applied={applied}")
    return applied


def write_changes_delete(
    table: str,
    id_value: str,
    path: str | Path | None = None,
) -> int:
    """
    Appende/aggiorna nel file una riga {id: ..., _delete: true} per la tabella indicata.
    """
    if not id_value:
        return 0
    return write_changes_upsert(table, [{"id": id_value, "_delete": True}], path=path)


# ---------------------------------------------------------------------------
# Seed generale da changes.json
# ---------------------------------------------------------------------------

def seed_from_changes(path: str | Path | None = None) -> int:
    """
    Applica le modifiche in changes.json in modo idempotente.
    - upsert per righe normali
    - delete se {_delete: true}
    Ritorna il numero di operazioni DB applicate.

    In caso di vincoli FK violati (IntegrityError) la singola riga viene
    saltata e si prosegue con le successive.
    """
    p = Path(path) if path is not None else CHANGES_PATH
    changes = load_changes(p)
    if not changes:
        return 0

    total = 0

    def _apply_table(session: Session, table_name: str, entries: List[Any]) -> int:
        model = TABLES.get(table_name)
        if model is None or not isinstance(entries, list):
            return 0

        applied_here = 0

        for raw_row in entries:
            if not isinstance(raw_row, dict):
                continue

            # DELETE
            if raw_row.get("_delete") is True:
                try:
                    deleted = _delete_db(session, model, raw_row)
                    session.commit()
                    applied_here += deleted
                except IntegrityError as e:
                    session.rollback()
                    logger.warning(
                        "[seed] IntegrityError on DELETE table=%s row=%s: %s – skipped",
                        table_name,
                        raw_row,
                        e,
                    )
                except Exception:
                    session.rollback()
                    raise
                continue

            # UPSERT
            row_db = _coerce_datetimes_for_db(raw_row)
            try:
                _upsert_db(session, model, row_db)
                session.commit()
                applied_here += 1
            except IntegrityError as e:
                session.rollback()
                logger.warning(
                    "[seed] IntegrityError on UPSERT table=%s row=%s: %s – skipped",
                    table_name,
                    row_db,
                    e,
                )
            except Exception:
                session.rollback()
                raise

        logger.info(f"[seed] {table_name}: applied {applied_here}")
        return applied_here

    with SessionLocal() as session:
        # Prima le tabelle nell’ordine esplicito
        for table_name in SEED_ORDER:
            entries = changes.get(table_name, [])
            if entries:
                total += _apply_table(session, table_name, entries)

        # Poi eventuali tabelle non elencate in SEED_ORDER
        for table_name, entries in changes.items():
            if table_name in SEED_ORDER:
                continue
            if entries:
                total += _apply_table(session, table_name, entries)

    logger.info(f"[seed] total applied: {total} from {p}")
    return total
def seed_disease_definitions_from_file(path: str | Path | None = None) -> int:
    """
    Legge un file in utils/ (plant_disease.txt / plant_disease.json /
    plant_disease_details.json) organizzato per famiglia e malattie, e fa:
      - upsert nella tabella 'disease' (una row per coppia family + disease)
      - upsert anche in changes.json (tabella 'disease')

    Ritorna il numero di righe DB applicate.
    """
    # 1) Risolvi il path del file
    if path is not None:
        p = Path(path)
    else:
        root = Path(__file__).resolve().parents[2]  # es. /app
        txt = root / "utils" / "plant_disease.txt"
        json_alt = root / "utils" / "plant_disease.json"
        details_alt = root / "utils" / "plant_disease_details.json"

        if txt.exists():
            p = txt
        elif json_alt.exists():
            p = json_alt
        elif details_alt.exists():
            p = details_alt
        else:
            logger.info("[seed_diseases] no plant_disease file found under utils/, skipping")
            return 0

    if not p.exists():
        logger.info(f"[seed_diseases] file not found: {p}, skipping")
        return 0

    # 2) Carica il JSON
    try:
        raw = p.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[seed_diseases] cannot parse JSON from {p}: {e}")
        return 0

    if not isinstance(payload, dict):
        logger.error(f"[seed_diseases] invalid structure in {p}: expected object at top-level")
        return 0

    # 3) Costruisci le righe pronte per DB + changes.json
    #    (una riga per coppia family_name + disease_name)
    rows: List[Dict[str, Any]] = []

    for family_name, diseases in payload.items():
        if not isinstance(diseases, dict):
            continue

        fam_name_str = str(family_name).strip()
        if not fam_name_str:
            continue

        for key, info in diseases.items():
            if not isinstance(info, dict):
                continue

            # Nel JSON il campo può essere "name" o dedotto dalla chiave
            name = str(info.get("name") or key).strip()
            if not name:
                continue

            description = (info.get("description") or "").strip()
            if not description:
                description = f"{name} - disease affecting ornamental plants."

            symptoms = info.get("symptoms") or []
            cure_tips = info.get("cure_tips") or []

            # normalizza i symptoms in lista di stringhe
            norm_symptoms: List[str] = []
            if isinstance(symptoms, str):
                norm_symptoms = [symptoms]
            elif isinstance(symptoms, list):
                for s in symptoms:
                    if isinstance(s, dict):
                        val = s.get("name") or s.get("label") or s.get("value")
                    else:
                        val = s
                    if val:
                        val_str = str(val).strip()
                        if val_str:
                            norm_symptoms.append(val_str)

            # normalizza i cure_tips in lista di stringhe
            norm_cure_tips: List[str] = []
            if isinstance(cure_tips, str):
                norm_cure_tips = [cure_tips]
            elif isinstance(cure_tips, list):
                for c in cure_tips:
                    if c:
                        c_str = str(c).strip()
                        if c_str:
                            norm_cure_tips.append(c_str)

            # Chiave stabile per questa coppia (family + disease)
            stable_key = f"{fam_name_str}::{name}"

            rows.append(
                {
                    "stable_key": stable_key,
                    "family_name": fam_name_str,
                    "name": name,
                    "description": description,
                    "symptoms": norm_symptoms or None,
                    "cure_tips": norm_cure_tips or None,
                }
            )

    if not rows:
        logger.info(f"[seed_diseases] no diseases found in {p}")
        return 0

    # 4) Upsert su DB (tabella disease) + changes.json
    applied_db = 0
    db_rows_for_changes: List[Dict[str, Any]] = []

    with SessionLocal() as session:
        # Mappa nome family -> id
        family_map: Dict[str, str] = {
            f.name: f.id for f in session.query(Family).all()
        }

        for r in rows:
            fam_name = r["family_name"]
            fam_id = family_map.get(fam_name)
            if not fam_id:
                logger.warning(
                    "[seed_diseases] family '%s' not found in DB; skipping disease '%s'",
                    fam_name,
                    r["name"],
                )
                continue

            row_db: Dict[str, Any] = {
                "id": _stable_disease_id(r["stable_key"]),
                "name": r["name"],
                "description": r["description"],
                "symptoms": r["symptoms"],
                "cure_tips": r["cure_tips"],
                "family_id": fam_id,
            }

            _upsert_db(session, Disease, row_db)
            applied_db += 1
            db_rows_for_changes.append(row_db)

        session.commit()

    # 5) Upsert anche in changes.json (così il seed è riproducibile)
    try:
        write_changes_upsert("disease", db_rows_for_changes)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[seed_diseases] failed to update changes.json: {e}")

    logger.info(f"[seed_diseases] applied {applied_db} disease rows from {p}")
    return applied_db
