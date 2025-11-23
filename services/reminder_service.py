from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, time
from typing import Dict, Any, Tuple, Optional

from models.base import SessionLocal
from models.entities import (
    WateringPlan,
    QuestionOption,
    UserQuestionAnswer,
    Plant,
    WateringLog,
    Reminder,
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

        In più:
        - crea anche un primo watering_log "programmato" per la pianta,
          con done_at = next_due_at e amount_ml dedotto dal piano,
          che farà da base per la pagina di innaffiatura.
        """

        with self._session() as s:
            try:
                # -------------------------------------------------
                # 1) Preferenze utente dal questionario
                # -------------------------------------------------
                prefs = self._load_answers_from_db(user_id)
                (
                    interval_days,
                    hour,
                    check_soil,
                    base_notes,
                ) = self._map_user_prefs_to_base_plan(prefs)

                # -------------------------------------------------
                # 2) Dati pianta → eventuale aggiustamento intervallo
                # -------------------------------------------------
                plant = s.query(Plant).filter(Plant.id == plant_id).first()
                interval_days, plant_notes = self._adjust_plan_with_plant_data(
                    interval_days,
                    plant,
                )

                # Note finali del piano
                notes = base_notes + " | " + plant_notes

                # -------------------------------------------------
                # 3) Calcolo della prima scadenza (next_due_at)
                # -------------------------------------------------
                next_due_at = datetime.utcnow() + timedelta(days=interval_days)
                next_due_at = next_due_at.replace(
                    hour=hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

                # -------------------------------------------------
                # 4) Calcolo dose consigliata in ml dal piano
                # -------------------------------------------------
                recommended_ml = self._estimate_amount_ml(plant, interval_days)

                # -------------------------------------------------
                # 5) Creazione WateringPlan principale
                # -------------------------------------------------
                plan = WateringPlan(
                    user_id=user_id,
                    plant_id=plant_id,
                    next_due_at=next_due_at,
                    interval_days=interval_days,
                    check_soil_moisture=1 if check_soil else 0,
                    notes=notes,
                )
                s.add(plan)

                # -------------------------------------------------
                # 6) Creazione PRIMO WateringLog in base al piano
                #    (uno "slot" programmato da mostrare in app)
                #    amount_ml = dose dedotta dal piano
                # -------------------------------------------------
                initial_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=next_due_at,          # data prevista
                    amount_ml=int(recommended_ml),
                    note=(
                        "SCHEDULED FROM PLAN "
                        f"(interval_days={interval_days}, "
                        f"ml={recommended_ml}, check_soil={bool(check_soil)})"
                    ),
                )
                s.add(initial_log)

                # Il commit viene gestito dal contextmanager _session()

            except Exception as e:
                print(
                    "[CRITICAL] create_plan_for_new_plant FALLITA MA NON BLOCCA NULLA:",
                    e,
                )

                # -------------------------------------------------
                #  Fallback: se qualcosa va storto, creiamo comunque
                #  un piano di emergenza + relativo log.
                # -------------------------------------------------
                fallback_next_due = datetime.utcnow().replace(
                    hour=9,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

                fallback_interval = 3
                # nessuna pianta a disposizione in errore → plant=None
                fallback_ml = self._estimate_amount_ml(
                    plant=None,
                    interval_days=fallback_interval,
                )

                fallback = WateringPlan(
                    user_id=user_id,
                    plant_id=plant_id,
                    next_due_at=fallback_next_due,
                    interval_days=fallback_interval,
                    check_soil_moisture=0,
                    notes="FALLBACK PLAN",
                )
                s.add(fallback)

                # WateringLog associato al piano di fallback
                fallback_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=fallback_next_due,
                    amount_ml=int(fallback_ml),
                    note=f"FALLBACK LOG - interval_days={fallback_interval}, ml={fallback_ml}",
                )
                s.add(fallback_log)

                # Commit sempre gestito da _session()

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
    #  STIMA AMOUNT ML DAL PIANO + PIANTA
    # ---------------------------------------------------------
    def _estimate_amount_ml(self, plant: Optional[Plant], interval_days: int) -> int:
        """
        Stima una dose d'acqua in ml basandosi su:
        - size della pianta
        - water_level
        - intervallo giorni del piano

        È una euristica semplice ma consistente, usata per:
        - primo log creato insieme al plan
        - fallback quando non c'è ancora uno storico di log
        """
        # base generico
        base_ml = 150

        if plant is not None:
            size = (plant.size or "medium").lower()
            wl = int(plant.water_level or 3)

            # size base
            if size == "small":
                base_ml = 100
            elif size == "medium":
                base_ml = 150
            elif size == "large":
                base_ml = 250
            elif size == "giant":
                base_ml = 350

            # aggiustamento per water_level
            if wl <= 2:
                base_ml = int(base_ml * 0.8)
            elif wl >= 4:
                base_ml = int(base_ml * 1.2)

        # aggiustamento per intervallo
        if interval_days >= 7:
            base_ml = int(base_ml * 1.1)
        elif interval_days <= 2:
            base_ml = int(base_ml * 0.9)

        # minimo sicurezza
        return max(50, base_ml)

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

    # ---------------------------------------------------------
    #  PUBLIC: l’utente ha innaffiato una pianta
    #          → crea log reale + aggiorna piano + nuovo log schedulato
    # ---------------------------------------------------------
    def register_watering_and_schedule_next(
        self,
        user_id: str,
        plant_id: str,
        amount_ml: int,
        note: Optional[str] = None,
        done_at: Optional[datetime] = None,
    ) -> dict:
        """
        - Crea un WateringLog REALE (l'utente ha innaffiato ora)
        - Gli ml di questa innaffiatura vengono dedotti dal piano:
            * se esiste già un log precedente → copia amount_ml da quello
            * altrimenti → calcola dose consigliata dal piano/plant
          (il parametro amount_ml passato può ancora fare override per
           questa singola innaffiatura, ma la dose base viene dal piano).
        - Aggiorna il WateringPlan.next_due_at spostandolo avanti di interval_days
          (se era in ritardo, lo porta più avanti finché è nel futuro)
        - Crea un NUOVO WateringLog "programmato" per la prossima scadenza
          con la stessa quantità ml usata nell’ultima innaffiatura
        - Crea anche un nuovo Reminder collegato alla pianta

        Ritorna un dict con info sul piano aggiornato e sulle date.
        """

        if done_at is None:
            done_at = datetime.utcnow()

        with self._session() as s:
            try:
                # =============================================
                # 1) Carico il piano esistente per (user, plant)
                # =============================================
                plan = (
                    s.query(WateringPlan)
                    .filter(
                        WateringPlan.user_id == user_id,
                        WateringPlan.plant_id == plant_id,
                    )
                    .first()
                )

                if not plan:
                    raise ValueError("No WateringPlan found for this user/plant")

                # sicurezza su interval_days
                interval_days = int(plan.interval_days or 3)

                # =============================================
                # 2) Carico pianta e ultimo log per derivare ML
                # =============================================
                plant = (
                    s.query(Plant)
                    .filter(Plant.id == plant_id)
                    .one_or_none()
                )

                last_log = (
                    s.query(WateringLog)
                    .filter(
                        WateringLog.user_id == user_id,
                        WateringLog.plant_id == plant_id,
                    )
                    .order_by(WateringLog.done_at.desc())
                    .first()
                )

                if last_log and last_log.amount_ml is not None and last_log.amount_ml > 0:
                    base_ml = int(last_log.amount_ml)
                else:
                    base_ml = self._estimate_amount_ml(plant, interval_days)

                # Se il client passa un valore, lo usiamo come override
                if amount_ml is not None:
                    amount_to_use = int(amount_ml)
                else:
                    amount_to_use = base_ml

                # =============================================
                # 3) LOG REALE: l'utente ha appena innaffiato
                # =============================================
                real_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=done_at,
                    amount_ml=amount_to_use,
                    note=note or "User watering",
                )
                s.add(real_log)

                # =============================================
                # 4) Calcolo nuova next_due_at del piano
                # =============================================
                base = plan.next_due_at or done_at
                next_due = base

                # se il piano era "in ritardo", sposto in avanti
                while next_due <= done_at:
                    next_due = next_due + timedelta(days=interval_days)

                plan.next_due_at = next_due

                # =============================================
                # 5) Creo il NUOVO log "programmato" per la prossima volta
                #    (slot futuro, amount_ml = stessa dose dell’ultima innaffiatura)
                # =============================================
                scheduled_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=next_due,           # data prevista futura
                    amount_ml=amount_to_use,    # stessa quantità usata ora
                    note=(
                        f"SCHEDULED FROM PLAN "
                        f"(interval_days={interval_days}, ml={amount_to_use})"
                    ),
                )
                s.add(scheduled_log)

                # =============================================
                # 6) Nuovo Reminder per la prossima scadenza
                # =============================================
                if plant is not None:
                    title = (
                        f"Water {plant.common_name or plant.scientific_name or 'your plant'}"
                    )
                else:
                    title = "Water your plant"

                rem = Reminder(
                    user_id=user_id,
                    title=title,
                    note=note,
                    scheduled_at=next_due,
                    done_at=None,
                    recurrence_rrule=None,
                    entity_type="plant",
                    entity_id=plant_id,
                )
                s.add(rem)

                # =============================================
                # 7) Commit
                # =============================================
                s.commit()

                return {
                    "ok": True,
                    "plan_id": str(plan.id),
                    "plant_id": plant_id,
                    "last_watered_at": done_at.isoformat(),
                    "next_due_at": next_due.isoformat(),
                    "interval_days": interval_days,
                    "amount_ml_used": amount_to_use,
                }

            except Exception as e:
                s.rollback()
                print("[ERROR] register_watering_and_schedule_next failed:", e)
                return {
                    "ok": False,
                    "error": str(e),
                }
