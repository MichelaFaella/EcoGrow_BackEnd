from __future__ import annotations

import json, os, re, unicodedata
from functools import lru_cache
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from sqlalchemy import select, func
from models.base import SessionLocal
from models.entities import Plant, UserPlant, Family, PlantPhoto
from models.scripts.replay_changes import write_changes_upsert


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
        Ritorna l'intero dict dell'item (o None).
        """
        data = self._load_house_plants()
        q_norm = self._normalize(scientific_name or "")
        if not q_norm:
            return None

        q_tokens = q_norm.split()
        rx = self._build_ordered_regex(q_tokens)

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
            if all(tok in lat_norm for tok in q_tokens):
                score += 50
            # C) prefix su genere
            if len(q_tokens) == 1 and lat_norm.startswith(q_tokens[0]):
                score += 25
            # D) contenimento semplice
            if q_norm in lat_norm:
                score += 10

            if score > 0:
                candidates.append((score, item))

        if not candidates:
            return None

        # best score; a parità preferisci latin più corto (più specifico)
        candidates.sort(key=lambda x: (-x[0], len((x[1].get("latin") or ""))))
        return candidates[0][1]

    # =======================
    # Getters dal JSON
    # =======================
    def get_family(self, scientific_name: str) -> Optional[str]:
        """
        Dato uno scientific_name (anche parziale) ritorna l'ID della Family nel DB,
        cercando la family nel JSON tramite matching fuzzy/regex.
        """
        it = self._match_houseplant_item(scientific_name)
        if not it:
            return None

        matched_family_name = (it.get("family") or it.get("name") or "").strip()
        if not matched_family_name:
            return None

        with self.Session() as s:
            fam = s.query(Family).filter(func.lower(Family.name) == matched_family_name.lower()).first()
            return str(fam.id) if fam else None

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
                select(Plant.id, Plant.scientific_name, Plant.common_name, UserPlant.nickname, UserPlant.location_note)
                .join(UserPlant, UserPlant.plant_id == Plant.id)
                .where(UserPlant.user_id == user_id)
                .order_by(Plant.common_name.nulls_last(), Plant.scientific_name)
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
