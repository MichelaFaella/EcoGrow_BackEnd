import json, os, re
from typing import List, Dict
from sqlalchemy import select, func
from models.base import SessionLocal
from models.entities import Plant, UserPlant, Family, PlantPhoto


class RepositoryService:
    def __init__(self):
        self.Session = SessionLocal

    def get_family(self, scientific_name: str) -> str:
        file_path = os.path.join(os.path.dirname(__file__), "..", "utils", "house_plants.json")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        def normalize(text: str) -> str:
            return re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()

        sci_norm = normalize(scientific_name)

        matched_family_name = None
        for item in data:
            latin = item.get("latin")
            if not latin:
                continue

            latin_norm = normalize(latin)

            # Match se uno contiene l’altro (bi-direzionale, anche parziale)
            if latin_norm in sci_norm or sci_norm in latin_norm:
                matched_family_name = item.get("family") or item.get("name")
                break

            # Match se tutte le parole del più corto sono nel più lungo
            short, long = (sci_norm, latin_norm) if len(sci_norm) < len(latin_norm) else (latin_norm, sci_norm)
            if all(word in long for word in short.split()):
                matched_family_name = item.get("family") or item.get("name")
                break

        if not matched_family_name:
            return None

        with self.Session() as s:
            fam = s.query(Family).filter(func.lower(Family.name) == matched_family_name.lower()).first()
            return str(fam.id) if fam else None

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
