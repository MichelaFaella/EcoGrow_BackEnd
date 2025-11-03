from typing import List, Dict
from sqlalchemy import select, func
from models.base import SessionLocal
from models.entities import Plant, UserPlant, Family, PlantPhoto
from sqlalchemy.orm import selectinload
class RepositoryService:
    def __init__(self):
        self.Session = SessionLocal

    def get_plants_by_user(self, user_id: str) -> List[Dict]:
        """
        Ritorna le piante possedute dall'utente come lista di dict JSON-serializzabili.
        """
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
        """
        Ritorna tutte le Family con conteggio piante collegate.
        """
        with SessionLocal() as session:
            # Conta quante Plant hanno quella family (1:N)
            q = (
                select(Family.id, Family.name, func.count(Plant.id).label("plants_count"))
                .select_from(Family)
                .join(Plant, Plant.family_id == Family.id, isouter=True)
                .group_by(Family.id, Family.name)
                .order_by(Family.name.asc())
            )
            rows = session.execute(q).all()
            return [
                {
                    "id": fid,
                    "name": name,
                    "plants_count": int(count or 0),
                }
                for (fid, name, count) in rows
            ]
        

    def get_all_plants_catalog(self) -> List[Dict]:
        """
        Ritorna tutte le piante con alcune info di base + family name e conteggio foto.
        """
        with SessionLocal() as s:
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