from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, time
from typing import Dict, Any, Tuple

from models.base import SessionLocal
from models.entities import (
    UserPlant,
    WateringPlan,
    QuestionOption,
    UserQuestionAnswer,
    Plant,
)


class ReminderService:

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    @contextmanager
    def _session(self):
        s = self._session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ---------------------------------------------------------
    #  PUBLIC: crea piano SOLO quando si aggiunge una pianta
    # ---------------------------------------------------------
    def create_plan_for_new_plant(self, user_id: str, plant_id: str):
        """
        Genera un watering_plan combinando:
        - preferenze utente (questionario)
        - caratteristiche della pianta
        """

        with self._session() as s:
            try:
                prefs = self._load_answers_from_db(user_id)
                interval_days, hour, check_soil, base_notes = self._map_user_prefs_to_base_plan(prefs)

                plant = s.query(Plant).filter(Plant.id == plant_id).first()
                interval_days, plant_notes = self._adjust_plan_with_plant_data(interval_days, plant)

                notes = base_notes + " | " + plant_notes

                next_due_at = datetime.utcnow() + timedelta(days=interval_days)
                next_due_at = next_due_at.replace(hour=hour, minute=0, second=0, microsecond=0)

                plan = WateringPlan(
                    user_id=user_id,
                    plant_id=plant_id,
                    next_due_at=next_due_at,
                    interval_days=interval_days,
                    check_soil_moisture=1 if check_soil else 0,
                    notes=notes,
                )
                s.add(plan)

            except Exception as e:
                print("[CRITICAL] create_plan_for_new_plant FALLITA MA NON BLOCCA NULLA:", e)
                # creiamo comunque un piano di emergenza
                fallback = WateringPlan(
                    user_id=user_id,
                    plant_id=plant_id,
                    next_due_at=datetime.utcnow().replace(hour=9, minute=0),
                    interval_days=3,
                    check_soil_moisture=0,
                    notes="FALLBACK PLAN",
                )
                s.add(fallback)

    # ---------------------------------------------------------
    #  BASE PLAN (SOLO QUESTIONARIO)
    # ---------------------------------------------------------
    def _map_user_prefs_to_base_plan(self, answers: Dict[str, Any]):
        """
        Restituisce:
            interval_days, hour, check_soil_moisture, notes
        """

        # Prima risposte
        q = lambda key: str(answers.get(key, ""))

        # Q1: frequenza
        q1_map = {
            "1": 3,   # weekdays only
            "2": 7,   # weekends
            "3": 3,   # any day
            "4": 2,   # every other day
        }
        interval_days = q1_map.get(q("q1"), 3)

        # Q2: fascia oraria
        q2_map = {
            "1": 8,
            "2": 13,
            "3": 19,
            "4": 9,
        }
        hour = q2_map.get(q("q2"), 9)

        # Q6: eco → soil moisture?
        q6_map = {
            "1": False,
            "2": True,
            "3": True,
            "4": True,
        }
        check_soil = q6_map.get(q("q6"), False)

        notes = f"base_interval={interval_days}, hour={hour}, eco_check={check_soil}"

        return interval_days, hour, check_soil, notes

    # ---------------------------------------------------------
    #  APPLY PLANT DATA (water_level, difficulty, size)
    # ---------------------------------------------------------
    def _adjust_plan_with_plant_data(self, interval_days: int, plant: Plant):
        notes = ""

        # ---- water_level ----
        wl = plant.water_level or 3  # fallback medium
        if wl == 1:
            interval_days += 3
            notes += "water_level=very_low; "
        elif wl == 2:
            interval_days += 1
            notes += "water_level=low; "
        elif wl == 3:
            notes += "water_level=medium; "
        elif wl == 4:
            interval_days -= 1
            notes += "water_level=high; "
        elif wl == 5:
            interval_days -= 2
            notes += "water_level=very_high; "

        # ---- difficulty ----
        diff = plant.difficulty or 3  # fallback medium
        if diff >= 4:
            interval_days -= 1
            notes += "difficulty=high; "
        elif diff == 1:
            interval_days += 1
            notes += "difficulty=easy; "

        # ---- size ----
        size = plant.size or "medium"
        if size == "small":
            interval_days += 1
            notes += "size=small; "
        elif size == "giant":
            interval_days -= 1
            notes += "size=giant; "

        interval_days = max(1, interval_days)

        return interval_days, notes

    # ---------------------------------------------------------
    #  LOAD USER PREFERENCES
    # ---------------------------------------------------------
    def _load_answers_from_db(self, user_id: str) -> Dict[str, str]:
        session = self._session_factory()
        try:
            rows = (
                session.query(
                    UserQuestionAnswer.question_id,
                    QuestionOption.position,
                )
                .join(QuestionOption, QuestionOption.id == UserQuestionAnswer.option_id)
                .filter(UserQuestionAnswer.user_id == user_id)
                .order_by(
                    UserQuestionAnswer.question_id,
                    UserQuestionAnswer.answered_at.desc(),
                )
                .all()
            )

            latest = {}
            seen = set()

            for qid, pos in rows:
                if qid not in seen:
                    latest[qid] = str(pos)
                    seen.add(qid)

            # ➕ Patch: garantiamo che ci siano valori di fallback
            latest.setdefault("q1", "3")  # Any day
            latest.setdefault("q2", "1")  # Morning
            latest.setdefault("q6", "1")  # Not eco

            return latest

        except Exception as e:
            print("[ERROR] _load_answers_from_db FALLITA:", e)
            # ritorno fallback sicuro
            return {"q1": "3", "q2": "1", "q6": "1"}

        finally:
            session.close()

