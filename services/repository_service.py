from __future__ import annotations

import base64
import json, os, re, unicodedata
from functools import lru_cache
from datetime import datetime, date
from io import BytesIO
from typing import List, Dict, Optional, Tuple

from PIL import Image
from sqlalchemy import select, func
from models.base import SessionLocal
from models.entities import Plant, UserPlant, Family, PlantPhoto
from models.scripts.replay_changes import write_changes_upsert
from models.entities import Question
from datetime import datetime, timedelta
from models.entities import Question, WateringPlan,Reminder


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

        # Usa già il JSON caricato/cachato
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

        # Cerco nel DB la Family corrispondente
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
        nickname: Optional[str] = None,
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
        nickname = (nickname or "").strip() or None
        location_note = (location_note or "").strip() or None

        with self.Session() as s:
            plant = s.get(Plant, plant_id)
            if not plant:
                raise ValueError("Plant not found")

            up = s.get(UserPlant, (user_id, plant_id))
            if up:
                changed = False
                if overwrite:
                    if up.nickname != nickname:
                        up.nickname = nickname; changed = True
                    if up.location_note != location_note:
                        up.location_note = location_note; changed = True
                    if up.since != since_date:
                        up.since = since_date; changed = True
                else:
                    if nickname is not None and nickname != up.nickname:
                        up.nickname = nickname; changed = True
                    if location_note is not None and location_note != up.location_note:
                        up.location_note = location_note; changed = True
                    if since is not None and since_date != up.since:
                        up.since = since_date; changed = True

                if changed:
                    s.commit()
                    write_changes_upsert("user_plant", [{
                        "user_id": user_id,
                        "plant_id": plant_id,
                        "nickname": up.nickname,
                        "location_note": up.location_note,
                        "since": up.since.isoformat() if up.since else None,
                    }])

                return {
                    "user_id": user_id,
                    "plant_id": plant_id,
                    "nickname": up.nickname,
                    "location_note": up.location_note,
                    "since": up.since.isoformat() if up.since else None,
                }

            # Non esiste: crea
            up = UserPlant(
                user_id=user_id,
                plant_id=plant_id,
                nickname=nickname,
                location_note=location_note,
                since=since_date,
            )
            s.add(up)
            s.commit()

            write_changes_upsert("user_plant", [{
                "user_id": user_id,
                "plant_id": plant_id,
                "nickname": up.nickname,
                "location_note": up.location_note,
                "since": up.since.isoformat() if up.since else None,
            }])

            return {
                "user_id": user_id,
                "plant_id": plant_id,
                "nickname": up.nickname,
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
                    UserPlant.nickname,
                    UserPlant.location_note,
                )
                .select_from(Plant)
                .join(UserPlant, UserPlant.plant_id == Plant.id)
                .where(UserPlant.user_id == user_id)
                # niente .nulls_last() che dava problemi in alcune combinazioni
                .order_by(Plant.common_name, Plant.scientific_name)
            )
            rows = s.execute(stmt).all()
            return [
                {
                    "id": r.id,
                    "scientific_name": r.scientific_name,
                    "common_name": r.common_name,
                    "nickname": r.nickname,
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

    def create_default_questions_for_user(self, user_id: str, session=None) -> List[Question]:
        """
        Create, for a newly registered user, a copy of the template questions.
        If a session is passed, use it (same transaction as user_add).
        Returns the list of created Question objects (does NOT commit if the session is external).
        """
        # Load question templates from question.json (cached in self._question_templates_cache)
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

        questions: List[Question] = []
        try:
            for tpl in templates:
                options = tpl.get("options") or []
                q = Question(
                    user_id=user_id,
                    text=tpl["text"],
                    type=tpl.get("type", "single_choice"),
                    options_json={"options": options},
                    active=True,
                    user_answer=None,
                    answered_at=None,
                )
                session.add(q)
                questions.append(q)

            if owns_session:
                session.commit()

            return questions
        finally:
            if owns_session:
                session.close()

    def get_questions_for_user(self, user_id: str) -> List[Dict]:
        """
        Restituisce le domande del questionario per un dato utente,
        con le opzioni già spacchettate e l'eventuale risposta salvata.
        """
        with self.Session() as s:
            rows = (
                s.query(Question)
                .filter(Question.user_id == user_id, Question.active.is_(True))
                .order_by(Question.id)
                .all()
            )

            out: List[Dict] = []
            for q in rows:
                options = []
                if isinstance(q.options_json, dict):
                    raw_opts = q.options_json.get("options") or []
                    if isinstance(raw_opts, list):
                        options = [str(o) for o in raw_opts]

                out.append(
                    {
                        "id": str(q.id),
                        "text": q.text,
                        "type": q.type,
                        "options": options,
                        # tipicamente "1", "2", "3" o "4"
                        "user_answer": q.user_answer,
                        "answered_at": q.answered_at.isoformat() if q.answered_at else None,
                    }
                )
            return out
        
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
        if time_pref == 1:      # Morning (07-10)
            hour = 8
        elif time_pref == 2:    # Lunch
            hour = 13
        elif time_pref == 3:    # Evening
            hour = 19
        else:                   # I don't care
            hour = 9

        # 3) intervallo giorni dalla Q1
        if day_pref == 4:       # Every other day
            interval_days = 2
        else:
            interval_days = 3   # esempio: ogni 3 giorni di default

        # 4) prima scadenza: domani all'ora scelta
        next_due = (now + timedelta(days=1)).replace(
            hour=hour, minute=0, second=0, microsecond=0
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

        # 6) creo il primo Reminder (solo se il modello Reminder esiste nel DB)
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
            recurrence_rrule=None,  # in futuro possiamo codificare interval_days
            entity_type="plant",
            entity_id=plant_id,
        )
        session.add(rem)

        # Il commit lo fa la route /plant/add
        return wp


    def save_question_answers(self, user_id: str, answers: Dict[str, str]) -> None:
        """
        Salva le risposte dell'utente.

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
            q_rows = (
                s.query(Question)
                .filter(Question.id.in_(q_ids))
                .all()
            )

            by_id = {str(q.id): q for q in q_rows}

            # 1) Prima controllo che TUTTI gli ID passati siano validi
            invalid_ids = []
            for qid in answers.keys():
                q = by_id.get(qid)
                if not q or str(q.user_id) != str(user_id):
                    invalid_ids.append(qid)

            if invalid_ids:
                # niente commit, sollevo errore di validazione
                raise ValueError(f"Invalid question IDs for this user: {', '.join(invalid_ids)}")

            # 2) Se sono tutti validi, aggiorno le risposte
            for qid, ans in answers.items():
                q = by_id[qid]
                q.user_answer = str(ans)   # "1","2","3","4"
                q.answered_at = now

            s.commit()


    def get_user_reminder_preferences(self, user_id: str, session=None) -> dict:
        """
        Legge le Question dell'utente e tira fuori le preferenze utili
        per i reminders/ watering plan.
        Per ora usiamo solo:
        - Q1: When do you prefer to take care of your plants?
        - Q2: At what time of day are you usually available?
        Ritorna un dict semplice, es: {"day_pref": 1, "time_pref": 3}
        """
        owns_session = False
        if session is None:
            session = self.Session()
            owns_session = True

        try:
            questions = (
                session.query(Question)
                .filter(Question.user_id == user_id)
                .all()
            )

            day_pref = None
            time_pref = None

            for q in questions:
                if not q.user_answer:
                    continue
                text = (q.text or "").strip()
                try:
                    idx = int(str(q.user_answer))
                except ValueError:
                    continue

                if "When do you prefer to take care of your plants?" in text:
                    day_pref = idx
                elif "At what time of day are you usually available?" in text:
                    time_pref = idx

            prefs = {
                "day_pref": day_pref,   # 1..4 o None
                "time_pref": time_pref, # 1..4 o None
            }
            return prefs
        finally:
            if owns_session:
                session.close()

    def get_full_plant_info(self, plant_id: str) -> Optional[Dict]:
        """
        Restituisce tutte le info della pianta + foto base64 compressa.
        """
        with self.Session() as s:
            plant = s.query(Plant).filter(Plant.id == plant_id).first()
            if not plant:
                return None

            # Family
            family_name = None
            family_description = None
            if plant.family_id:
                fam = s.query(Family).filter(Family.id == plant.family_id).first()
                if fam:
                    family_name = fam.name
                    family_description = getattr(fam, "description", None)

            # Foto → Base64 compresso
            photo_base64 = None
            photo_row = (
                s.query(PlantPhoto)
                .filter(PlantPhoto.plant_id == plant_id)
                .order_by(PlantPhoto.id.asc())
                .first()
            )

            if photo_row:
                image_path = getattr(photo_row, "path", None)  # <-- CAMBIA QUI se diverso
                if image_path and os.path.exists(image_path):
                    # Compressione vera dell’immagine
                    img = Image.open(image_path)

                    # Ridimensiona se molto grande
                    img.thumbnail((800, 800), Image.Resampling.LANCZOS)

                    # Salva in buffer JPEG compresso
                    buffer = BytesIO()
                    img.save(buffer, format="JPEG", quality=60, optimize=True)  # qualità regolabile
                    buffer.seek(0)

                    # Converto in base64
                    photo_base64 = base64.b64encode(buffer.read()).decode("utf-8")

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
