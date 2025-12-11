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
                    hour=0,
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
                    done_at=next_due_at,  # data prevista
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
                    hour=0,
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
            "1": 3,  # weekdays only
            "2": 7,  # weekends
            "3": 3,  # any day
            "4": 2,  # every other day
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
    @staticmethod
    def _adjust_plan_with_plant_data(interval_days: int, plant: Plant):
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

            # Patch: garantiamo che ci siano valori di fallback
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

        with self._session() as s:
            try:
                # ===== 1) Recupero piano =====
                plan = (
                    s.query(WateringPlan)
                    .filter(
                        WateringPlan.user_id == user_id,
                        WateringPlan.plant_id == plant_id,
                    )
                    .first()
                )
                if not plan:
                    raise ValueError("No WateringPlan found")

                interval_days = int(plan.interval_days or 3)

                # ===== 2) Ora reale e intervallo del giorno =====
                now_real = done_at or datetime.utcnow()

                today_midnight = now_real.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                tomorrow_midnight = today_midnight + timedelta(days=1)

                # ===== 3) Pianta =====
                plant = (
                    s.query(Plant)
                    .filter(Plant.id == plant_id)
                    .one_or_none()
                )

                # ===== 4) Ultimo log PRIMA di oggi (storico) =====
                last_before_today = (
                    s.query(WateringLog)
                    .filter(
                        WateringLog.user_id == user_id,
                        WateringLog.plant_id == plant_id,
                        WateringLog.done_at < today_midnight,
                    )
                    .order_by(WateringLog.done_at.desc())
                    .first()
                )

                if last_before_today and last_before_today.amount_ml:
                    base_ml = int(last_before_today.amount_ml)
                else:
                    base_ml = self._estimate_amount_ml(plant, interval_days)

                real_ml = amount_ml if amount_ml else base_ml

                # --------------------------------------------------
                # 5) 🔥 Pulisci TUTTI i log di OGGI per quella pianta
                #    (sia programmati che eventuali reali "strani")
                # --------------------------------------------------
                s.query(WateringLog).filter(
                    WateringLog.user_id == user_id,
                    WateringLog.plant_id == plant_id,
                    WateringLog.done_at >= today_midnight,
                    WateringLog.done_at < tomorrow_midnight,
                ).delete(synchronize_session=False)

                # --------------------------------------------------
                # 6) Crea UN SOLO log REALE per oggi (ora vera)
                # --------------------------------------------------
                real_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=now_real,  # ORA REALE
                    amount_ml=real_ml,
                    note=note or "User watering",
                )
                s.add(real_log)

                # --------------------------------------------------
                # 7) Calcola next_due_at (sempre mezzanotte del giorno futuro)
                # --------------------------------------------------
                next_due = today_midnight + timedelta(days=interval_days)
                next_due = next_due.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                plan.next_due_at = next_due

                # --------------------------------------------------
                # 8) Elimina eventuali log programmati DUPLICATI sulla nuova data
                # --------------------------------------------------
                s.query(WateringLog).filter(
                    WateringLog.user_id == user_id,
                    WateringLog.plant_id == plant_id,
                    WateringLog.done_at == next_due,
                ).delete(synchronize_session=False)

                # --------------------------------------------------
                # 9) Crea NUOVO log PROGRAMMATO per la prossima volta (mezzanotte)
                #    → puoi scegliere se usare real_ml o una nuova stima
                # --------------------------------------------------
                scheduled_ml = real_ml  # oppure: self._estimate_amount_ml(plant, interval_days)

                future_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=next_due,  # SEMPRE MEZZANOTTE
                    amount_ml=scheduled_ml,
                    note="SCHEDULED FROM PLAN",
                )
                s.add(future_log)

                # --------------------------------------------------
                # 10) Reminder
                # --------------------------------------------------
                s.query(Reminder).filter(
                    Reminder.user_id == user_id,
                    Reminder.entity_type == "plant",
                    Reminder.entity_id == plant_id,
                ).delete(synchronize_session=False)

                title = (
                    f"Water {plant.common_name or plant.scientific_name or 'your plant'}"
                    if plant else "Water your plant"
                )

                new_rem = Reminder(
                    user_id=user_id,
                    title=title,
                    note=note,
                    scheduled_at=next_due,
                    done_at=None,
                    recurrence_rrule=None,
                    entity_type="plant",
                    entity_id=plant_id,
                )
                s.add(new_rem)

                # commit gestito dal context manager
                return {
                    "ok": True,
                    "plant_id": plant_id,
                    "last_watered_at": now_real.isoformat(),
                    "next_due_at": next_due.isoformat(),
                    "interval_days": interval_days,
                    "amount_ml_used": real_ml,
                }

            except Exception as e:
                s.rollback()
                print("[ERROR] register_watering_and_schedule_next:", e)
                return {"ok": False, "error": str(e)}

    # ---------------------------------------------------------
    #  PUBLIC: Annulla l’annaffiatura di oggi
    # ---------------------------------------------------------
    def undo_watering(self, user_id: str, plant_id: str) -> dict:
        """
        Undo dell'annaffiatura di OGGI per una pianta:
        - rimuove tutti i log di oggi (reali + eventuali programmati)
        - rimuove i log futuri (scheduled) per quella pianta
        - ricrea 1 log programmato oggi a mezzanotte
        - ripristina next_due_at a oggi (mezzanotte)
        """

        with self._session() as s:
            try:
                # ===== 1) Recupero piano =====
                plan = (
                    s.query(WateringPlan)
                    .filter(
                        WateringPlan.user_id == user_id,
                        WateringPlan.plant_id == plant_id,
                    )
                    .first()
                )
                if not plan:
                    raise ValueError("No WateringPlan found")

                interval_days = int(plan.interval_days or 3)

                now = datetime.utcnow()
                today_midnight = now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                tomorrow_midnight = today_midnight + timedelta(days=1)

                # ===== 2) Pianta =====
                plant = (
                    s.query(Plant)
                    .filter(Plant.id == plant_id)
                    .one_or_none()
                )

                # ===== 3) Elimina TUTTI i log di OGGI (qualsiasi nota/orario)
                deleted_today = s.query(WateringLog).filter(
                    WateringLog.user_id == user_id,
                    WateringLog.plant_id == plant_id,
                    WateringLog.done_at >= today_midnight,
                    WateringLog.done_at < tomorrow_midnight,
                ).delete(synchronize_session=False)

                # ===== 4) Elimina log FUTURI della pianta (scheduled dopo oggi)
                deleted_future = s.query(WateringLog).filter(
                    WateringLog.user_id == user_id,
                    WateringLog.plant_id == plant_id,
                    WateringLog.done_at >= tomorrow_midnight,
                ).delete(synchronize_session=False)

                # ===== 5) Trova ultimo log PRIMA di oggi per dosaggio
                prev_log = (
                    s.query(WateringLog)
                    .filter(
                        WateringLog.user_id == user_id,
                        WateringLog.plant_id == plant_id,
                        WateringLog.done_at < today_midnight,
                    )
                    .order_by(WateringLog.done_at.desc())
                    .first()
                )

                if prev_log and prev_log.amount_ml:
                    scheduled_ml = int(prev_log.amount_ml)
                else:
                    scheduled_ml = self._estimate_amount_ml(plant, interval_days)

                # ===== 6) Ricrea log programmato a MEZZANOTTE DI OGGI
                scheduled_log = WateringLog(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    plant_id=plant_id,
                    done_at=today_midnight,
                    amount_ml=scheduled_ml,
                    note="SCHEDULED FROM PLAN (UNDO)",
                )
                s.add(scheduled_log)

                # ===== 7) next_due_at = oggi a mezzanotte
                plan.next_due_at = today_midnight

                # ===== 8) Reset reminder
                s.query(Reminder).filter(
                    Reminder.user_id == user_id,
                    Reminder.entity_type == "plant",
                    Reminder.entity_id == plant_id,
                ).delete(synchronize_session=False)

                title = (
                    f"Water {plant.common_name or plant.scientific_name or 'your plant'}"
                    if plant else "Water your plant"
                )

                new_rem = Reminder(
                    user_id=user_id,
                    title=title,
                    note=None,
                    scheduled_at=today_midnight,
                    done_at=None,
                    recurrence_rrule=None,
                    entity_type="plant",
                    entity_id=plant_id,
                )
                s.add(new_rem)

                return {
                    "ok": True,
                    "plant_id": plant_id,
                    "restored_to": today_midnight.isoformat(),
                    "deleted_today_logs": deleted_today,
                    "deleted_future_logs": deleted_future,
                }

            except Exception as e:
                s.rollback()
                print("[ERROR undo_watering]:", e)
                return {"ok": False, "error": str(e)}

    @staticmethod
    def send_push_notification(token: str, title: str, body: str) -> None:
        """
        MOCK: backend attualmente configurato SENZA Firebase.
        Questa funzione non invia push reali, ma logga solo cosa manderebbe.
        Quando vorrai attivare Firebase, potrai implementare qui la logica reale.
        """
        print(f"[PUSH MOCK] Would send notification to token={token}: {title} - {body}")

    def check_due_plants_for_user_using_repo(self, user_id: str, repo):
        print("\n[ReminderService] START check_due_plants_for_user_using_repo")
        print(f"→ Checking plants for USER: {user_id}")

        try:
            print("→ Fetching watering overview from repo...")
            overview = repo.get_watering_overview_for_user(user_id)
            print("→ OVERVIEW LOADED:")
            print(overview)
        except Exception as e:
            print("→ ERROR loading overview:", e)
            return {"ok": False, "error": str(e)}

        now = datetime.utcnow()
        print(f"→ CURRENT UTC TIME: {now}")

        due_plants = []

        for entry in overview:
            plant_name = entry.get("plant_name")
            print("\n--- Checking plant:", plant_name, " ---")

            logs = entry.get("logs", [])
            print("→ LOGS for plant:")
            print(logs)

            plant_is_due = False

            for log in logs:
                print("\n   → Checking log:", log)

                note = (log.get("note") or "").upper()
                done_at_str = log.get("done_at")

                print(f"     note={note}")
                print(f"     done_at={done_at_str}")

                if not done_at_str:
                    print("     → SKIP: done_at missing")
                    continue

                try:
                    dt = datetime.fromisoformat(done_at_str)
                    print(f"     → Parsed datetime: {dt}")
                except:
                    print("     → ERROR parsing datetime")
                    continue

                if "SCHEDULED" in note and dt <= now:
                    print("     → This plant is DUE!")
                    plant_is_due = True
                    break
                else:
                    print("     → NOT due")

            if plant_is_due:
                print(f"→ Adding plant {plant_name} to DUE list")
                due_plants.append(plant_name)
            else:
                print(f"→ Plant {plant_name} NOT due")

        print("\nFINAL DUE PLANTS:")
        print(due_plants)

        print("[ReminderService] END check_due_plants_for_user_using_repo\n")

        return {
            "ok": True,
            "due": len(due_plants) > 0,
            "due_plants": due_plants,
            "message": (
                "You have plants that need watering."
                if due_plants else None
            )
        }


