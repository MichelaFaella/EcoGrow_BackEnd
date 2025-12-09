from __future__ import annotations

import uuid
import base64
import json
import os
import re
import unicodedata
from functools import lru_cache
from datetime import datetime, date, timedelta
from io import BytesIO
from typing import List, Dict, Optional, Tuple

from PIL import Image
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import Any

from models.base import SessionLocal
from models.scripts.replay_changes import write_changes_upsert, write_changes_delete
from models.entities import (
    Plant,
    UserPlant,
    Family,
    PlantPhoto,
    Question,
    QuestionOption,
    UserQuestionAnswer,
    WateringPlan,
    Reminder,
    WateringLog, Friendship, User, SharedPlant, Disease, PlantDisease,
)


class RepositoryService:
    def __init__(self):
        self.Session = SessionLocal

    # =======================
    # Helpers JSON / Matching
    # =======================
    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        t = re.sub(r"[^a-z0-9\s]", " ", t.lower())
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def _build_disease_output(disease, image_base64: str):
        # symptoms può essere list o dict
        raw_sym = getattr(disease, "symptoms", None)
        if isinstance(raw_sym, list):
            symptoms = [str(x) for x in raw_sym if x]
        elif isinstance(raw_sym, dict):
            symptoms = [str(k) for k, v in raw_sym.items() if v]
        else:
            symptoms = []

        raw_cure = getattr(disease, "cure_tips", None)
        if isinstance(raw_cure, list):
            cure_tips = [str(x) for x in raw_cure if x]
        elif isinstance(raw_cure, dict):
            cure_tips = [str(k) for k, v in raw_cure.items() if v]
        else:
            cure_tips = []

        return {
            "id": str(disease.id),
            "name": disease.name,
            "description": disease.description,
            "symptoms": symptoms,
            "cure_tips": cure_tips,
            "family_id": str(disease.family_id),
            "image_base64": image_base64,
        }


    @staticmethod
    def _build_ordered_regex(tokens: List[str]) -> re.Pattern:
        # token1.*token2.*token3 (match ordinato ma permissivo)
        body = r".*".join(map(re.escape, tokens))
        return re.compile(body, flags=re.IGNORECASE)

    @lru_cache(maxsize=1)
    def _load_house_plants(self) -> List[dict]:
        file_path = os.path.join(os.path.dirname(__file__), "..", "utils", "house_plants.json")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _match_houseplant_item(self, scientific_name: str) -> Optional[dict]:
        """
        Trova l'item migliore dal JSON usando:
        - regex ordinata sui token (token1.*token2...)
        - tutti i token contenuti (ordine libero)
        - prefix su genere (quando un solo token)
        - contenimento semplice

        Se NON trova nulla e il nome ha più token (es. "Rosa chinensis"),
        fa un fallback sul SOLO genere (primo token, es. "Rosa").
        Ritorna l'intero dict dell'item (o None).
        """
        data = self._load_house_plants()
        q_norm = self._normalize(scientific_name or "")
        if not q_norm:
            return None

        q_tokens = q_norm.split()

        def _search_with_tokens(tokens: List[str]) -> Optional[dict]:
            rx = self._build_ordered_regex(tokens)
            candidates: List[Tuple[int, dict]] = []

            for item in data:
                latin = (item.get("latin") or "").strip()
                if not latin:
                    continue
                lat_norm = self._normalize(latin)

                score = 0
                # A) regex ordinata
                if rx.search(lat_norm):
                    score += 100
                # B) tutti i token presenti (ordine libero)
                if all(tok in lat_norm for tok in tokens):
                    score += 50
                # C) prefix su genere (solo se un token)
                if len(tokens) == 1 and lat_norm.startswith(tokens[0]):
                    score += 25
                # D) contenimento semplice
                if " ".join(tokens) in lat_norm:
                    score += 10

                if score > 0:
                    candidates.append((score, item))

            if not candidates:
                return None

            # best score; a parità preferisci latin più corto (più specifico)
            candidates.sort(key=lambda x: (-x[0], len((x[1].get("latin") or ""))))
            return candidates[0][1]

        # 1) primo tentativo: nome completo (es. "rosa chinensis")
        item = _search_with_tokens(q_tokens)
        if item is not None:
            return item

        # 2) fallback: se c'è almeno genere + qualcosa, prova solo il genere
        if len(q_tokens) > 1:
            genus = q_tokens[0]
            print(f"[RepositoryService] Fallback match sul genere: {genus!r} per {scientific_name!r}")
            item = _search_with_tokens([genus])
            if item is not None:
                return item

        # 3) niente da fare
        return None

    # =======================
    # Getters dal JSON
    # =======================
    def get_family(self, scientific_name: str) -> Optional[str]:
        """
        Dato uno scientific_name (da PlantNet), prova a:
        - fare match con il campo "latin" del file house_plants.json
          usando l'helper _match_houseplant_item
        - ricavare il nome di family (item["family"] o item["name"])
        - cercare quella family nel DB
        - restituire l'id della family, oppure None se non trovata.
        """
        print(f"[get_family] scientific_name={scientific_name!r}")

        item = self._match_houseplant_item(scientific_name)
        if not item:
            print(f"[get_family] NO MATCH in JSON for scientific_name={scientific_name!r}")
            return None

        latin = (item.get("latin") or "").strip()
        matched_family_name = (item.get("family") or item.get("name") or "").strip()

        print(
            f"[get_family] MATCH item: latin={latin!r}, "
            f"matched_family_name={matched_family_name!r}"
        )

        if not matched_family_name:
            print(f"[get_family] Item has no 'family'/'name' field, giving up.")
            return None

        with self.Session() as s:
            fam = (
                s.query(Family)
                .filter(func.lower(Family.name) == matched_family_name.lower())
                .first()
            )

            if not fam:
                print(
                    f"[get_family] NO DB family row for name={matched_family_name!r}"
                )
                return None

            print(f"[get_family] DB family found: id={fam.id}, name={fam.name!r}")
            return str(fam.id)

    def get_common_name(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return None
        commons = it.get("common") or []
        return commons[0] if isinstance(commons, list) and commons else None

    def get_size_for(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        return (it.get("size") or None) if it else None  # es. 'small' | 'medium' | 'large' | 'giant'

    def get_levels_for(self, scientific_name: str) -> Tuple[Optional[int], Optional[int]]:
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return (None, None)
        return (it.get("watering_level"), it.get("lighting_level"))

    def get_temps_for(self, scientific_name: str) -> Tuple[Optional[int], Optional[int]]:
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return (None, None)
        tmin = (it.get("tempmin") or {}).get("celsius")
        tmax = (it.get("tempmax") or {}).get("celsius")
        return (tmin, tmax)

    def get_category_for(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        return (it.get("category") or None) if it else None

    def get_climate_for(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        return (it.get("climate") or None) if it else None

    def get_origin_for(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        return (it.get("origin") or None) if it else None

    def get_use_for(self, scientific_name: str) -> Optional[str]:
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return None
        use = it.get("use")
        if isinstance(use, list):
            return ", ".join([u for u in use if u])
        return use or None

    def get_plant_defaults(self, scientific_name: str) -> Dict:
        """
        Restituisce un dict con default mappati ai nomi colonna di Plant:
        - common_name, category, climate, origin, use
        - water_level, light_level
        - min_temp_c, max_temp_c
        - size
        (La family resta fuori: usa get_family per l'ID.)
        """
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return {}

        commons = it.get("common") or []
        common_name = commons[0] if isinstance(commons, list) and commons else None

        tmin = (it.get("tempmin") or {}).get("celsius")
        tmax = (it.get("tempmax") or {}).get("celsius")

        use_val = it.get("use")
        if isinstance(use_val, list):
            use_val = ", ".join([u for u in use_val if u])

        return {
            "common_name": common_name,
            "category": it.get("category"),
            "climate": it.get("climate"),
            "origin": it.get("origin"),
            "use": use_val or None,
            "water_level": it.get("watering_level"),
            "light_level": it.get("lighting_level"),
            "min_temp_c": tmin,
            "max_temp_c": tmax,
            "size": it.get("size"),
            "tips": it.get("tips"),
        }

    # =======================
    # Link user <-> plant
    # =======================
    @staticmethod
    def _parse_since_to_date(since_val) -> Optional[date]:
        """Accetta date, datetime o stringhe ISO/YYYY-MM-DD e restituisce date oppure None."""
        if not since_val:
            return None
        if isinstance(since_val, date) and not isinstance(since_val, datetime):
            return since_val
        if isinstance(since_val, datetime):
            return since_val.date()
        if isinstance(since_val, str):
            try:
                dt = datetime.fromisoformat(since_val)
                return dt.date()
            except Exception:
                try:
                    return datetime.strptime(since_val, "%Y-%m-%d").date()
                except Exception:
                    raise ValueError("since deve essere in formato YYYY-MM-DD o ISO 8601")
        raise ValueError("Formato non valido per 'since'")

    def ensure_user_plant_link(
            self,
            *,
            user_id: str,
            plant_id: str,
            location_note: Optional[str] = None,
            since: Optional[date | datetime | str] = None,
            overwrite: bool = False,
    ) -> Dict:
        """
        Crea in modo idempotente la relazione user_plant (user_id, plant_id).
        - Se non esiste: la crea.
        - Se esiste: aggiorna i campi passati (o tutti se overwrite=True).
        - Normalizza 'since' a date.
        - Restituisce un dict con i valori correnti salvati.
        Lancia ValueError se la pianta non esiste o se 'since' non è valido.
        """
        since_date = self._parse_since_to_date(since) if since else None
        location_note = (location_note or "").strip() or None

        with self.Session() as s:
            plant = s.get(Plant, plant_id)
            if not plant:
                raise ValueError("Plant not found")

            up = s.get(UserPlant, (user_id, plant_id))
            if up:
                changed = False
                if overwrite:
                    if up.location_note != location_note:
                        up.location_note = location_note
                        changed = True
                    if up.since != since_date:
                        up.since = since_date
                        changed = True
                else:
                    if location_note is not None and location_note != up.location_note:
                        up.location_note = location_note
                        changed = True
                    if since is not None and since_date != up.since:
                        up.since = since_date
                        changed = True

                if changed:
                    s.commit()
                    write_changes_upsert("user_plant", [{
                        "user_id": user_id,
                        "plant_id": plant_id,
                        "location_note": up.location_note,
                        "since": up.since.isoformat() if up.since else None,
                    }])

                return {
                    "user_id": user_id,
                    "plant_id": plant_id,
                    "location_note": up.location_note,
                    "since": up.since.isoformat() if up.since else None,
                }

            # Non esiste: crea
            up = UserPlant(
                user_id=user_id,
                plant_id=plant_id,
                location_note=location_note,
                since=since_date,
            )
            s.add(up)
            s.commit()

            write_changes_upsert("user_plant", [{
                "user_id": user_id,
                "plant_id": plant_id,
                "location_note": up.location_note,
                "since": up.since.isoformat() if up.since else None,
            }])

            return {
                "user_id": user_id,
                "plant_id": plant_id,
                "location_note": up.location_note,
                "since": up.since.isoformat() if up.since else None,
            }

    # =======================
    # Query su DB
    # =======================
    def get_plants_by_user(self, user_id: str) -> List[Dict]:
        with self.Session() as s:
            stmt = (
                select(
                    Plant.id,
                    Plant.scientific_name,
                    Plant.common_name,
                    UserPlant.location_note,
                )
                .select_from(Plant)
                .join(UserPlant, UserPlant.plant_id == Plant.id)
                .where(UserPlant.user_id == user_id)
                .order_by(Plant.common_name, Plant.scientific_name)
            )
            rows = s.execute(stmt).all()
            return [
                {
                    "id": r.id,
                    "scientific_name": r.scientific_name,
                    "common_name": r.common_name,
                    "location_note": r.location_note,
                }
                for r in rows
            ]

    def get_all_families(self) -> List[Dict]:
        with self.Session() as s:
            q = (
                select(Family.id, Family.name, func.count(Plant.id).label("plants_count"))
                .select_from(Family)
                .join(Plant, Plant.family_id == Family.id, isouter=True)
                .group_by(Family.id, Family.name)
                .order_by(Family.name.asc())
            )
            rows = s.execute(q).all()
            return [
                {
                    "id": fid,
                    "name": name,
                    "plants_count": int(count or 0),
                }
                for (fid, name, count) in rows
            ]

    def get_all_plants_catalog(self) -> List[Dict]:
        with self.Session() as s:
            q = (
                select(
                    Plant.id,
                    Plant.scientific_name,
                    Plant.common_name,
                    Plant.category,
                    Plant.climate,
                    Plant.water_level,
                    Plant.light_level,
                    Family.name.label("family_name"),
                    func.count(PlantPhoto.id).label("photos_count"),
                )
                .select_from(Plant)
                .join(Family, Plant.family_id == Family.id, isouter=True)
                .join(PlantPhoto, PlantPhoto.plant_id == Plant.id, isouter=True)
                .group_by(
                    Plant.id,
                    Plant.scientific_name,
                    Plant.common_name,
                    Plant.category,
                    Plant.climate,
                    Plant.water_level,
                    Plant.light_level,
                    Family.name,
                )
                .order_by(Plant.scientific_name.asc())
            )
            rows = s.execute(q).all()

            return [
                {
                    "id": r.id,
                    "scientific_name": r.scientific_name,
                    "common_name": r.common_name,
                    "category": r.category,
                    "climate": r.climate,
                    "water_level": r.water_level,
                    "light_level": r.light_level,
                    "family_name": r.family_name,
                    "photos_count": int(r.photos_count or 0),
                }
                for r in rows
            ]

    # =======================
    # QUESTIONARIO - seeding
    # =======================
    def create_default_questions_for_user(self, user_id: str, session=None) -> List[Question]:
        """
        Compat: nome storico.
        Ora in realtà fa il SEED globale delle domande se non esistono ancora.

        Legge da question.json:
        [
          {"text": "...", "type": "...", "options": ["opt1","opt2","opt3","opt4"]},
          ...
        ]

        Ritorna la lista di Question presenti a DB (nuove o già esistenti).
        """
        # cache locale del JSON
        if not hasattr(self, "_question_templates_cache"):
            file_path = os.path.join(os.path.dirname(__file__), "..", "question.json")
            file_path = os.path.realpath(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                self._question_templates_cache = json.load(f)
        templates = self._question_templates_cache

        owns_session = False
        if session is None:
            session = self.Session()
            owns_session = True

        try:
            existing_questions = session.query(Question).order_by(Question.id).all()
            if existing_questions:
                return existing_questions

            created: List[Question] = []

            for tpl in templates:
                options = tpl.get("options") or []

                q = Question(
                    text=tpl["text"],
                    type=tpl.get("type", "single_choice"),
                    active=True,
                )
                session.add(q)
                session.flush()  # per avere q.id

                for idx, opt_text in enumerate(options, start=1):
                    label = chr(ord("A") + (idx - 1))  # 'A','B','C','D'
                    opt = QuestionOption(
                        question_id=q.id,
                        label=label,
                        text=str(opt_text),
                        is_correct=False,
                        position=idx,
                    )
                    session.add(opt)

                created.append(q)

            if owns_session:
                session.commit()

            return created
        finally:
            if owns_session:
                session.close()

    # =======================
    # QUESTIONARIO - lettura
    # =======================
    def get_questions_for_user(self, user_id: str) -> List[Dict]:
        """
        Restituisce tutte le domande attive con le opzioni associate
        e l'eventuale risposta già data dall'utente.

        Output per ogni domanda:
        {
            "id": "<question_id>",
            "text": "...",
            "type": "...",
            "options": ["opt1", "opt2", "opt3", "opt4"],
            "user_answer": "1" | "2" | "3" | "4" | None,
            "answered_at": "2025-01-01T12:00:00" | None
        }
        """
        with self.Session() as s:
            questions: List[Question] = (
                s.query(Question)
                .filter(Question.active.is_(True))
                .order_by(Question.id)
                .all()
            )

            if not questions:
                return []

            answers: List[UserQuestionAnswer] = (
                s.query(UserQuestionAnswer)
                .filter(
                    UserQuestionAnswer.user_id == user_id,
                    UserQuestionAnswer.question_id.in_([q.id for q in questions]),
                )
                .all()
            )
            answers_by_qid: Dict[str, UserQuestionAnswer] = {
                a.question_id: a for a in answers

            }

            out: List[Dict] = []

            for q in questions:
                # opzioni ordinate per position (1..4)
                opts: List[QuestionOption] = sorted(q.options, key=lambda o: o.position)
                options_text = [o.text for o in opts]

                u_ans = answers_by_qid.get(q.id)
                user_answer_idx: Optional[int] = None
                answered_at: Optional[datetime] = None

                if u_ans is not None:
                    answered_at = u_ans.answered_at
                    # mappa option_id -> indice (1..4)
                    for idx, opt in enumerate(opts, start=1):
                        if opt.id == u_ans.option_id:
                            user_answer_idx = idx
                            break

                out.append(
                    {
                        "id": str(q.id),
                        "text": q.text,
                        "type": q.type,
                        "options": options_text,
                        "user_answer": str(user_answer_idx) if user_answer_idx is not None else None,
                        "answered_at": answered_at.isoformat() if answered_at else None,
                    }
                )

            return out

    # =======================
    # FRIENDSHIP
    # =======================

    def get_user_id_by_short(self, short_id: str) -> Optional[str]:
        """
        Restituisce l'ID completo dell'utente il cui UUID inizia con short_id.
        short_id = prime 8 cifre dell'UUID.
        """
        print(f"[RepositoryService] get_user_id_by_short -> short_id={short_id}")

        if not short_id or len(short_id) < 3:
            return None

        with self.Session() as s:
            row = (
                s.query(User)
                .filter(User.id.like(f"{short_id}%"))
                .first()
            )

            if not row:
                print(f"[RepositoryService] No user found for short_id={short_id}")
                return None

            print(f"[RepositoryService] Found user: {row.id}")
            return str(row.id)

    def get_existing_friendship(self, user_a: str, user_b: str) -> Optional[Friendship]:
        """
        Controlla se una friendship esiste già in una delle due direzioni.
        """
        print(f"[RepositoryService] get_existing_friendship {user_a} <-> {user_b}")

        with self.Session() as s:
            fr = (
                s.query(Friendship)
                .filter(
                    ((Friendship.user_id_a == user_a) & (Friendship.user_id_b == user_b)) |
                    ((Friendship.user_id_a == user_b) & (Friendship.user_id_b == user_a))
                )
                .first()
            )

            if fr:
                print(f"[RepositoryService] Existing friendship found: {fr.id}")
            else:
                print("[RepositoryService] No existing friendship")

            return fr

    def create_friendship(self, data: dict) -> Friendship:
        """
        Crea una friendship (senza controllare duplicati).
        """
        print(f"[RepositoryService] create_friendship data={data}")

        with self.Session() as s:
            fr = Friendship(**data)
            s.add(fr)
            s.commit()
            s.refresh(fr)

            write_changes_upsert("friendship", [{
                "id": fr.id,
                "user_id_a": fr.user_id_a,
                "user_id_b": fr.user_id_b,
                "status": fr.status,
                "created_at": fr.created_at.isoformat() if fr.created_at else None,
                "updated_at": fr.updated_at.isoformat() if fr.updated_at else None,
            }])

            print(f"[RepositoryService] Friendship created id={fr.id}")
            return fr

    def get_friendships_for_user(self, user_id: str):
        """
        Restituisce tutte le amicizie dove compare user_id.
        """
        print(f"[RepositoryService] get_friendships_for_user user_id={user_id}")

        with self.Session() as s:
            rows = (
                s.query(Friendship)
                .filter(
                    (Friendship.user_id_a == user_id) |
                    (Friendship.user_id_b == user_id)
                )
                .order_by(Friendship.created_at.desc())
                .all()
            )

            print(f"[RepositoryService] Found {len(rows)} friendships.")
            return rows

    def get_friendship_by_id(self, fid: str) -> Optional[Friendship]:
        print(f"[RepositoryService] get_friendship_by_id fid={fid}")
        with self.Session() as s:
            fr = s.get(Friendship, fid)
            if fr:
                print(f"[RepositoryService] Found friendship {fid}")
            else:
                print(f"[RepositoryService] Friendship {fid} NOT found")
            return fr

    def delete_friendship(self, fid: str) -> None:
        print(f"[RepositoryService] delete_friendship fid={fid}")
        with self.Session() as s:
            fr = s.get(Friendship, fid)
            if not fr:
                print(f"[RepositoryService] Nothing to delete (not found)")
                return

            s.delete(fr)
            s.commit()

            write_changes_delete("friendship", fid)
            print(f"[RepositoryService] Deleted friendship {fid}")
    
    def update_friendship(self, fid: str, data: dict) -> Optional[Friendship]:
        print(f"[RepositoryService] update_friendship fid={fid}, data={data}")
        with self.Session() as s:
            fr = s.get(Friendship, fid)
            if not fr:
                print("[RepositoryService] Friendship not found")
                return None

            for k, v in data.items():
                setattr(fr, k, v)

            s.commit()

            write_changes_upsert("friendship", [{
                "id": fr.id,
                "user_id_a": fr.user_id_a,
                "user_id_b": fr.user_id_b,
                "status": fr.status,
                "created_at": fr.created_at.isoformat() if fr.created_at else None,
            }])

            return fr



    # ===========================
    # SHARED_PLANT
    # ===========================

    def create_shared_plant(self, data: dict):
        print(f"[RepositoryService] create_shared_plant data={data}")

        with self.Session() as s:
            sp = SharedPlant(**data)
            s.add(sp)
            s.commit()
            s.refresh(sp)

            write_changes_upsert("shared_plant", [{
                "id": sp.id,
                "owner_user_id": sp.owner_user_id,
                "recipient_user_id": sp.recipient_user_id,
                "plant_id": sp.plant_id,
                "can_edit": sp.can_edit,
                "created_at": sp.created_at.isoformat() if sp.created_at else None,
                "ended_sharing_at": sp.ended_sharing_at.isoformat() if sp.ended_sharing_at else None,
            }])

            print(f"[RepositoryService] SharedPlant created id={sp.id}")
            return sp

    def get_shared_plant_by_id(self, sid: str) -> Optional[SharedPlant]:
        print(f"[RepositoryService] get_shared_plant_by_id sid={sid}")
        with self.Session() as s:
            sp = s.get(SharedPlant, sid)
            if sp:
                print(f"[RepositoryService] Found shared plant {sid}")
            else:
                print(f"[RepositoryService] Shared plant {sid} NOT found")
            return sp

    def get_shared_plants_for_user(self, user_id: str):
        """
        Ritorna tutte le piante condivise ATTIVE (ended_sharing_at IS NULL)
        dove l’utente è owner o recipient.
        """
        print(f"[RepositoryService] get_shared_plants_for_user user_id={user_id}")

        with self.Session() as s:
            shared = (
                s.query(SharedPlant)
                .filter(
                    (
                            (SharedPlant.owner_user_id == user_id) |
                            (SharedPlant.recipient_user_id == user_id)
                    ) &
                    (SharedPlant.ended_sharing_at.is_(None))  # <-- 🔥 FILTRO CORRETTO
                )
                .order_by(SharedPlant.created_at.desc())
                .all()
            )

            print(f"[RepositoryService] Found {len(shared)} active shared plants.")

            out = []

            for sp in shared:

                # ==========================================================
                # SUPPORTA SIA MODELLO SQLALCHEMY CHE DICT
                # ==========================================================
                def get(obj, key):
                    if isinstance(obj, dict):
                        return obj.get(key)
                    return getattr(obj, key, None)

                plant_id = get(sp, "plant_id")
                owner_id = get(sp, "owner_user_id")
                recipient_id = get(sp, "recipient_user_id")
                created_at = get(sp, "created_at")
                can_edit = get(sp, "can_edit")

                # ---------------------------------------------------------
                # Identifica l’amico
                # ---------------------------------------------------------
                friend_id = recipient_id if owner_id == user_id else owner_id

                friend = s.query(User).filter(User.id == friend_id).first()

                # ---------------------------------------------------------
                # Info pianta
                # ---------------------------------------------------------
                plant = s.query(Plant).filter(Plant.id == plant_id).first()

                plant_name = plant.common_name if plant else None
                if not plant_name and plant:
                    plant_name = plant.scientific_name

                # ---------------------------------------------------------
                # FOTO
                # ---------------------------------------------------------
                photo = (
                    s.query(PlantPhoto)
                    .filter(PlantPhoto.plant_id == plant_id)
                    .order_by(PlantPhoto.order_index.asc())
                    .first()
                )

                photo_b64 = None
                if photo:
                    file_path = os.path.join("uploads", plant_id, photo.url)

                    try:
                        with open(file_path, "rb") as f:
                            photo_b64 = base64.b64encode(f.read()).decode("utf-8")
                    except Exception as e:
                        print(f"[WARN] Cannot read file {file_path}: {e}")

                # ---------------------------------------------------------
                # OUTPUT
                # ---------------------------------------------------------
                out.append({
                    "shared_id": str(get(sp, "id")),
                    "plant_id": str(plant_id),
                    "owner_user_id": str(owner_id),
                    "recipient_user_id": str(recipient_id),
                    "can_edit": can_edit,
                    "created_at": created_at.isoformat() if created_at else None,

                    "friend_first_name": friend.first_name if friend else None,
                    "friend_last_name": friend.last_name if friend else None,
                    "plant_name": plant_name,
                    "photo_base64": photo_b64,
                })

            return out

    def get_plant_basic_with_photo(self, plant_id: str):
        """
        Ritorna info base della pianta + prima foto in base64 (se esiste).
        Usata per sick/healthy plants.
        """
        with self.Session() as s:
            plant = s.query(Plant).filter(Plant.id == plant_id).first()
            if not plant:
                return None

            # Foto
            photo = (
                s.query(PlantPhoto)
                .filter(PlantPhoto.plant_id == plant_id)
                .order_by(PlantPhoto.order_index.asc())
                .first()
            )

            photo_b64 = None
            if photo:
                file_path = os.path.join("uploads", plant_id, photo.url)
                if os.path.exists(file_path):
                    try:
                        with open(file_path, "rb") as f:
                            photo_b64 = base64.b64encode(f.read()).decode("utf-8")
                    except:
                        pass

            return {
                "id": str(plant.id),
                "scientific_name": plant.scientific_name,
                "common_name": plant.common_name,
                "photo_base64": photo_b64,
                "family_id": plant.family_id,
                "category": plant.category,
                "climate": plant.climate,
                "difficulty": plant.difficulty,
                "origin": plant.origin,
                "light_level": plant.light_level,
                "min_temp_c": plant.min_temp_c,
                "max_temp_c": plant.max_temp_c,
            }

    def update_shared_plant(self, sid: str, data: dict):
        print(f"[RepositoryService] update_shared_plant sid={sid}, data={data}")
        with self.Session() as s:
            sp = s.get(SharedPlant, sid)
            if not sp:
                print("[RepositoryService] Shared plant not found")
                return None

            for k, v in data.items():
                setattr(sp, k, v)

            s.commit()

            write_changes_upsert("shared_plant", [{
                "id": sp.id,
                "owner_user_id": sp.owner_user_id,
                "recipient_user_id": sp.recipient_user_id,
                "plant_id": sp.plant_id,
                "can_edit": sp.can_edit,
                "created_at": sp.created_at.isoformat() if sp.created_at else None,
                "ended_sharing_at": sp.ended_sharing_at.isoformat() if sp.ended_sharing_at else None,
            }])

            return sp

    def delete_shared_plant(self, sid: str, user_id: str) -> bool:
        """
        Termina una condivisione (soft delete) impostando ended_sharing_at.
        Solo l'owner può rimuoverla.
        """
        print(f"[RepositoryService] soft-delete shared plant sid={sid}")

        with self.Session() as s:
            sp = s.get(SharedPlant, sid)
            if not sp:
                print("[RepositoryService] Not found")
                return False

            # Autorizzazione: solo l'owner può rimuovere la condivisione
            if sp.owner_user_id != user_id:
                print("[RepositoryService] Not authorized")
                return False

            # Soft delete
            sp.ended_sharing_at = datetime.utcnow()
            s.commit()

            # Devi usare upsert, NON update, perché non esiste
            write_changes_upsert("shared_plant", [{
                "id": sp.id,
                "owner_user_id": sp.owner_user_id,
                "recipient_user_id": sp.recipient_user_id,
                "plant_id": sp.plant_id,
                "can_edit": sp.can_edit,
                "created_at": sp.created_at.isoformat() if sp.created_at else None,
                "ended_sharing_at": sp.ended_sharing_at.isoformat() if sp.ended_sharing_at else None,
            }])

            print(f"[RepositoryService] Shared plant {sid} marked as ended")
            return True

    # =======================
    # QUESTIONARIO - scrittura
    # =======================
    def save_question_answers(self, user_id: str, answers: Dict[str, str]) -> None:
        """
        Salva le risposte dell'utente nel modello normalizzato.

        answers = {
            "<question_id>": "1",  # indice opzione 1..4 (stringa)
            "<question_id>": "3",
            ...
        }
        """
        if not answers:
            return

        now = datetime.utcnow()
        q_ids = list(answers.keys())

        with self.Session() as s:
            # carico le domande attive interessate
            questions: List[Question] = (
                s.query(Question)
                .filter(
                    Question.id.in_(q_ids),
                    Question.active.is_(True),
                )
                .all()
            )
            questions_by_id: Dict[str, Question] = {q.id: q for q in questions}

            # controllo che tutti gli ID siano validi
            invalid_ids = [qid for qid in q_ids if qid not in questions_by_id]
            if invalid_ids:
                raise ValueError(f"Invalid question IDs: {', '.join(invalid_ids)}")

            # risposte già presenti per questo utente su queste domande
            existing_answers: List[UserQuestionAnswer] = (
                s.query(UserQuestionAnswer)
                .filter(
                    UserQuestionAnswer.user_id == user_id,
                    UserQuestionAnswer.question_id.in_(q_ids),
                )
                .all()
            )
            existing_by_qid: Dict[str, UserQuestionAnswer] = {
                a.question_id: a for a in existing_answers
            }

            for qid, ans_value in answers.items():
                q = questions_by_id[qid]

                # parse indice 1..4
                try:
                    idx = int(str(ans_value))
                except ValueError:
                    raise ValueError(f"Invalid answer value for question {qid}: {ans_value!r}")

                # trova l'opzione con quella position
                opt = next((o for o in q.options if o.position == idx), None)
                if opt is None:
                    raise ValueError(f"No option at position {idx} for question {qid}")

                existing = existing_by_qid.get(qid)
                if existing is None:
                    # nuova risposta
                    new_answer = UserQuestionAnswer(
                        user_id=user_id,
                        question_id=qid,
                        option_id=opt.id,
                        answered_at=now,
                    )
                    s.add(new_answer)
                    existing_by_qid[qid] = new_answer
                else:
                    # update risposta esistente
                    existing.option_id = opt.id
                    existing.answered_at = now

            s.commit()

    # =======================
    # QUESTIONARIO - preferenze (per watering plan)
    # =======================
    def get_user_reminder_preferences(self, user_id: str, session=None) -> dict:
        """
        Legge le risposte dell'utente (UserQuestionAnswer) e tira fuori le
        preferenze utili per i reminders / watering plan.

        - Q1: When do you prefer to take care of your plants?
        - Q2: At what time of day are you usually available?

        Ritorna un dict:
        {
            "day_pref": 1..4 | None,
            "time_pref": 1..4 | None
        }
        """
        owns_session = False
        if session is None:
            session = self.Session()
            owns_session = True

        try:
            rows = (
                session.query(UserQuestionAnswer, Question, QuestionOption)
                .join(Question, UserQuestionAnswer.question_id == Question.id)
                .join(QuestionOption, UserQuestionAnswer.option_id == QuestionOption.id)
                .filter(UserQuestionAnswer.user_id == user_id)
                .all()
            )

            day_pref = None
            time_pref = None

            for uqa, q, opt in rows:
                text = (q.text or "").strip()
                idx = opt.position  # 1..4

                if "When do you prefer to take care of your plants?" in text:
                    day_pref = idx
                elif "At what time of day are you usually available?" in text:
                    time_pref = idx

            return {
                "day_pref": day_pref,
                "time_pref": time_pref,
            }
        finally:
            if owns_session:
                session.close()

    # =======================
    # WATERING PLAN di default
    # =======================
    def create_default_watering_plan_for_plant(
            self,
            session,
            user_id: str,
            plant_id: str,
    ):
        """
        Crea un WateringPlan di default per (user_id, plant_id)
        usando le preferenze del questionario e crea anche
        il primo Reminder collegato alla pianta.
        Va chiamata dentro una sessione esistente.
        """
        # 0) se esiste già un WP per (user, plant), non fare doppioni
        existing = (
            session.query(WateringPlan)
            .filter(
                WateringPlan.user_id == user_id,
                WateringPlan.plant_id == plant_id,
            )
            .first()
        )
        if existing:
            return existing

        # 1) prendo le preferenze dal questionario
        prefs = self.get_user_reminder_preferences(user_id, session=session)

        day_pref = prefs.get("day_pref") or 3  # fallback: Any day
        time_pref = prefs.get("time_pref") or 1  # fallback: Morning

        now = datetime.utcnow()

        # 2) orario dalla Q2
        if time_pref == 1:  # Morning (07-10)
            hour = 8
        elif time_pref == 2:  # Lunch
            hour = 13
        elif time_pref == 3:  # Evening
            hour = 19
        else:  # I don't care
            hour = 9

        # 3) intervallo giorni dalla Q1
        if day_pref == 4:  # Every other day
            interval_days = 2
        else:
            interval_days = 3  # esempio: ogni 3 giorni di default

        next_due = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # 5) creo il WateringPlan
        wp = WateringPlan(
            user_id=user_id,
            plant_id=plant_id,
            next_due_at=next_due,
            interval_days=interval_days,
            check_soil_moisture=False,
            notes="Auto-created from questionnaire preferences.",
        )
        session.add(wp)
        session.flush()  # così WP è persistito prima di creare il reminder

        # 6) creo il primo Reminder
        plant = session.query(Plant).filter(Plant.id == plant_id).one_or_none()
        if plant is not None:
            title = f"Water {plant.common_name or plant.scientific_name or 'your plant'}"
        else:
            title = "Water your plant"

        rem = Reminder(
            user_id=user_id,
            title=title,
            note=None,
            scheduled_at=next_due,
            done_at=None,
            recurrence_rrule=None,
            entity_type="plant",
            entity_id=plant_id,
        )
        session.add(rem)

        # Il commit lo fa la route /plant/add
        return wp

    # =======================
    # Info complete pianta
    # =======================
    def get_full_plant_info(self, plant_id: str) -> Optional[Dict]:
        """
        Restituisce tutte le info della pianta +
        foto base64 compressa (se presente).
        """
        with self.Session() as s:
            plant = (
                s.query(Plant)
                .filter(Plant.id == plant_id)
                .first()
            )
            if not plant:
                return None

            # ==========================
            # FAMILY INFO
            # ==========================
            family_name = None
            family_description = None
            if plant.family_id:
                fam = (
                    s.query(Family)
                    .filter(Family.id == plant.family_id)
                    .first()
                )
                if fam:
                    family_name = fam.name
                    family_description = getattr(fam, "description", None)

            # ==========================
            # FOTO PIANTA
            # ==========================
            photo_base64 = None

            # prendiamo la prima foto (order_index)
            photo_row = (
                s.query(PlantPhoto)
                .filter(PlantPhoto.plant_id == plant_id)
                .order_by(PlantPhoto.order_index.asc())
                .first()
            )

            if photo_row:
                # costruiamo path REALE del file
                # es: uploads/<plant_id>/<filename>.jpg
                base_dir = os.path.join("uploads", plant_id)
                image_path = os.path.join(base_dir, photo_row.url)

                print("[DEBUG PHOTO] Image path:", image_path)
                print("[DEBUG PHOTO] Exists? ->", os.path.exists(image_path))

                if os.path.exists(image_path):
                    try:
                        img = Image.open(image_path)

                        # ridimensioniamo se molto grande
                        img.thumbnail((800, 800), Image.Resampling.LANCZOS)

                        buffer = BytesIO()
                        img.save(buffer, format="JPEG", quality=60, optimize=True)
                        buffer.seek(0)

                        photo_base64 = base64.b64encode(buffer.read()).decode("utf-8")

                    except Exception as e:
                        print("[DEBUG PHOTO] ERROR opening/compressing image:", e)
                        photo_base64 = None
                else:
                    print("[DEBUG PHOTO] File not found on disk.")

            # ==========================
            # RETURN INFO
            # ==========================
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

    def get_family_by_name(self, family_name: str) -> Optional[str]:
        """
        Ritorna l'id della Family dato il nome (case-insensitive),
        oppure None se non trovata.
        """
        if not family_name:
            return None

        with self.Session() as s:
            fam = (
                s.query(Family)
                .filter(func.lower(Family.name) == family_name.lower())
                .first()
            )
            return str(fam.id) if fam else None

    # =======================
    # WATERING PAGE - overview (settimanale)
    # =======================
    def get_watering_overview_for_user(self, user_id: str) -> List[Dict]:
        """
        Restituisce TUTTI i log della settimana (7 giorni) per ogni pianta dell’utente:
        - log reali (ora reale)
        - log programmati (sempre a mezzanotte)
        - la pianta NON sparisce mai
        - frontend riceve done_at e amount_ml
        """

        now = datetime.utcnow()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)

        with self.Session() as s:

            # ----------------------------
            # 1) Tutte le piante dell’utente
            # ----------------------------
            plants = (
                s.query(WateringPlan, Plant)
                .join(Plant, Plant.id == WateringPlan.plant_id)
                .filter(WateringPlan.user_id == user_id)
                .all()
            )

            result = []

            for wp, plant in plants:

                # ----------------------------
                # 2) tutti i log della settimana
                # ----------------------------
                logs = (
                    s.query(WateringLog)
                    .filter(
                        WateringLog.user_id == user_id,
                        WateringLog.plant_id == wp.plant_id,
                        WateringLog.done_at >= week_start,
                        WateringLog.done_at < week_end,
                    )
                    .order_by(WateringLog.done_at.asc())
                    .all()
                )

                # ----------------------------
                # 3) se NON esiste nessun log → crea quello programmato
                # ----------------------------
                if not logs:
                    scheduled_dt = wp.next_due_at.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                    scheduled_log = WateringLog(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        plant_id=wp.plant_id,
                        done_at=scheduled_dt,
                        amount_ml=150,  # dose base
                        note="SCHEDULED",
                    )
                    s.add(scheduled_log)
                    s.commit()
                    logs = [scheduled_log]

                # ----------------------------
                # 4) foto compressa
                # ----------------------------
                try:
                    info = self.get_full_plant_info(str(wp.plant_id))
                    photo_base64 = info.get("photo_base64")
                except Exception:
                    photo_base64 = None

                # ----------------------------
                # 5) log → lista di dizionari
                # ----------------------------
                logs_dict = [
                    {
                        "done_at": log.done_at.isoformat(),
                        "amount_ml": log.amount_ml,
                        "note": log.note,
                    }
                    for log in logs
                ]

                # ----------------------------
                # 6) output finale
                # ----------------------------
                result.append(
                    {
                        "plant_id": str(wp.plant_id),
                        "plant_name": plant.common_name or plant.scientific_name,
                        "logs": logs_dict,
                        "photo_base64": photo_base64,
                    }
                )

            return result

    def get_family_symptoms(self, family_id: str):
        """
        Restituisce una lista unica di sintomi per tutte le disease della famiglia.
        Esclude:
          - NULL
          - liste vuote
        Elimina duplicati mantenendo l’ordine.
        """
        print(f"[Repository] get_family_symptoms family_id={family_id}")

        with self.Session() as s:
            diseases = (
                s.query(Disease)
                .filter(Disease.family_id == family_id)
                .order_by(Disease.name.asc())
                .all()
            )

            seen = set()
            result = []

            for d in diseases:
                raw = d.symptoms

                if not raw:
                    continue

                # supporto JSON lista o dict
                if isinstance(raw, list):
                    items = [x for x in raw if x]
                elif isinstance(raw, dict):
                    items = [k for k, v in raw.items() if v]
                else:
                    items = []

                for sym in items:
                    if sym not in seen:
                        seen.add(sym)
                        result.append(sym)

            return {
                "family_id": family_id,
                "symptoms": result,
            }

    def enrich_disease_prediction(self, family_id: str, predicted_label: str, image_base64: str):
        print(f"[enrich_disease_prediction] family={family_id}, label={predicted_label}")

        label = (predicted_label or "").strip()
        if not label:
            label = "Unknown"

        predicted_norm = self._normalize(label)

        with self.Session() as s:
            diseases = (
                s.query(Disease)
                .filter(Disease.family_id == family_id)
                .all()
            )

            # MATCH ESATTO
            for d in diseases:
                if self._normalize(d.name) == predicted_norm:
                    out = self._build_disease_output(d, image_base64)
                    out["photo_base64"] = image_base64  # compat con la route
                    return out

            # MATCH CONTIENE
            for d in diseases:
                if predicted_norm and predicted_norm in self._normalize(d.name):
                    out = self._build_disease_output(d, image_base64)
                    out["photo_base64"] = image_base64
                    return out

        # FALLBACK: Unknown o non trovata
        return {
            "id": None,
            "name": label,
            "description": None,
            "symptoms": [],
            "cure_tips": [],
            "severity": None,
            "family_id": family_id,
            "photo_base64": image_base64,
        }

    # =======================
    # NUOVE FUNZIONI PER AI DISEASE DETECTION
    # =======================

    def create_plant_disease_record(
            self,
            *,
            plant_id: str,
            disease_id: Optional[str],
            status: str = "detected",
            severity: Optional[int] = None,
            notes: Optional[str] = None,
            detected_at: Optional[date] = None,
    ) -> Optional[PlantDisease]:

        detected_at = detected_at or date.today()

        with self.Session() as s:
            # 1️⃣ Verifica plant
            plant = s.get(Plant, plant_id)
            if not plant:
                print("[ERROR] Plant not found:", plant_id)
                return None

            # 2️⃣ Verifica disease (solo se disease_id è valido)
            disease = None
            if disease_id:
                disease = s.get(Disease, disease_id)
                if not disease:
                    print("[ERROR] Disease not found:", disease_id)
                    return None
            else:
                # Unknown → non salvare un record plant_disease
                print("[INFO] No disease_id provided → skipping plant_disease creation")
                return None

            # 3️⃣ Crea record
            record = PlantDisease(
                plant_id=plant_id,
                disease_id=disease_id,
                detected_at=detected_at,
                severity=severity,
                notes=notes,
                status=status,
            )
            s.add(record)
            s.commit()
            s.refresh(record)

            # Tracciamento modifiche
            write_changes_upsert("plant_disease", [{
                "id": record.id,
                "plant_id": plant_id,
                "disease_id": disease_id,
                "detected_at": detected_at.isoformat(),
                "severity": severity,
                "notes": notes,
                "status": status,
            }])

            return record

    def add_plant_photo(
            self,
            *,
            plant_id: str,
            image_base64: str,
            caption: Optional[str] = None,
    ) -> Optional[PlantPhoto]:

        # Decodifica immagine
        raw_bytes = base64.b64decode(image_base64)

        with self.Session() as s:
            # 1️⃣ Verifica plant
            plant = s.get(Plant, plant_id)
            if not plant:
                print("[ERROR] Plant not found:", plant_id)
                return None

            # 2️⃣ Prepara path
            folder = os.path.join("uploads", plant_id)
            os.makedirs(folder, exist_ok=True)

            filename = f"{uuid.uuid4()}.jpg"
            file_path = os.path.join(folder, filename)

            # Salva file
            with open(file_path, "wb") as f:
                f.write(raw_bytes)

            # 3️⃣ Ordine foto
            count = (
                        s.query(func.count(PlantPhoto.id))
                        .filter(PlantPhoto.plant_id == plant_id)
                        .scalar()
                    ) or 0

            # 4️⃣ Salva record DB
            photo = PlantPhoto(
                plant_id=plant_id,
                url=filename,
                caption=caption,
                order_index=count,
            )
            s.add(photo)
            s.commit()
            s.refresh(photo)

            write_changes_upsert("plant_photo", [{
                "id": photo.id,
                "plant_id": plant_id,
                "url": filename,
                "caption": caption,
                "order_index": count,
                "created_at": photo.created_at.isoformat() if photo.created_at else None,
            }])

            return photo

    def update_user_plant_status(
            self,
            *,
            user_id: str,
            plant_id: str,
            new_status: str,
    ) -> Optional[UserPlant]:

        with self.Session() as s:
            up = s.get(UserPlant, (user_id, plant_id))
            if not up:
                print("[ERROR] UserPlant link not found:", user_id, plant_id)
                return None

            up.health_status = new_status

            s.commit()
            s.refresh(up)

            write_changes_upsert("user_plant", [{
                "user_id": user_id,
                "plant_id": plant_id,
                "health_status": new_status,
                "location_note": up.location_note,
                "since": up.since.isoformat() if up.since else None,
            }])

            return up



