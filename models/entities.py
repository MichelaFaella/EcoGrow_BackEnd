from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional
import uuid
from enum import Enum
from sqlalchemy import Enum as SAEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base  # usa la tua Base/engine/SessionLocal


# ======================================================================
# CORE
# ======================================================================

def gen_uuid() -> str:
    return str(uuid.uuid4())

class Family(Base):
    __tablename__ = "family"

    id:   Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 1:N  (una family ha molte piante)
    plants: Mapped[list["Plant"]] = relationship(back_populates="family", lazy="selectin")
class SizeEnum(str, Enum):
    PICCOLO = "piccolo"
    MEDIO   = "medio"
    GRANDE  = "grande"
    GIGANTE = "gigante"

class Plant(Base):
    __tablename__ = "plant"


    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    scientific_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    common_name: Mapped[Optional[str]] = mapped_column(String(255))
    use: Mapped[str] = mapped_column("use", String(100), nullable=False)  # UseEnum logico
    origin: Mapped[Optional[str]] = mapped_column(String(255))
    water_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    light_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    min_temp_c: Mapped[int] = mapped_column(Integer, nullable=False)
    max_temp_c: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # ENUM/logici
    category: Mapped[str] = mapped_column(String(100), nullable=False)   # CategoryEnum logico
    climate:  Mapped[str] = mapped_column(String(100), nullable=False)   # ClimateEnum logico
    pests:    Mapped[Optional[dict]] = mapped_column(MySQLJSON)           # es. ["aphid","whitefly"]

    size: Mapped[SizeEnum] = mapped_column(
        SAEnum(SizeEnum, name="size_enum", native_enum=True),
        nullable=False,
        default=SizeEnum.MEDIO,
    )
    # NEW: 1:N con Family
    family_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("family.id", ondelete="RESTRICT", onupdate="CASCADE"),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("water_level BETWEEN 1 AND 5", name="ck_plant_water_level"),
        CheckConstraint("light_level BETWEEN 1 AND 5", name="ck_plant_light_level"),
        CheckConstraint("min_temp_c < max_temp_c", name="ck_plant_temp_range"),
        Index("ix_plant_category_climate", "category", "climate"),
        Index("ix_plant_updated_at", "updated_at"),
        Index("ix_plant_family", "family_id"),
    )

    # relazioni
    family: Mapped[Optional["Family"]] = relationship(back_populates="plants", lazy="selectin")

    photos: Mapped[List["PlantPhoto"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PlantPhoto.order_index.asc()",
        lazy="selectin",
    )

    # rimosso: families (N↔N)
    diseases: Mapped[List["PlantDisease"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    owners: Mapped[List["User"]] = relationship(
        secondary="user_plant",
        back_populates="plants",
        lazy="selectin",
    )

    watering_plans: Mapped[List["WateringPlan"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    watering_logs: Mapped[List["WateringLog"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    shared_records: Mapped[List["SharedPlant"]] = relationship(
        back_populates="plant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class PlantPhoto(Base):
    __tablename__ = "plant_photo"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)    
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    plant: Mapped["Plant"] = relationship(back_populates="photos")




# ======================================================================
# DISEASES
# ======================================================================

class Disease(Base):
    __tablename__ = "disease"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    treatment: Mapped[Optional[str]] = mapped_column(Text)

    plants: Mapped[List["PlantDisease"]] = relationship(
        back_populates="disease",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class PlantDisease(Base):
    __tablename__ = "plant_disease"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    disease_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("disease.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    detected_at: Mapped[Optional[date]] = mapped_column(Date)
    severity: Mapped[Optional[int]] = mapped_column(SmallInteger)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(50))

    plant: Mapped["Plant"] = relationship(back_populates="diseases")
    disease: Mapped["Disease"] = relationship(back_populates="plants")


# ======================================================================
# USERS & RELAZIONI
# ======================================================================

class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    plants: Mapped[List["Plant"]] = relationship(
        secondary="user_plant",
        back_populates="owners",
        lazy="selectin",
    )

    watering_plans: Mapped[List["WateringPlan"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    watering_logs: Mapped[List["WateringLog"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    questions: Mapped[List["Question"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    reminders: Mapped[List["Reminder"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    outgoing_shares: Mapped[List["SharedPlant"]] = relationship(
        foreign_keys="SharedPlant.owner_user_id",
        back_populates="owner_user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    incoming_shares: Mapped[List["SharedPlant"]] = relationship(
        foreign_keys="SharedPlant.recipient_user_id",
        back_populates="recipient_user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class UserPlant(Base):
    __tablename__ = "user_plant"
    __table_args__ = (
        UniqueConstraint("user_id", "plant_id", name="pk_user_plant"),
        Index("idx_up_plant", "plant_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    nickname: Mapped[Optional[str]] = mapped_column(String(100))
    location_note: Mapped[Optional[str]] = mapped_column(String(255))
    since: Mapped[Optional[date]] = mapped_column(Date)


class Friendship(Base):
    __tablename__ = "friendship"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id_a: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id_b: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Colonne generate per bloccare duplicati (a,b) == (b,a)
    user_min: Mapped[Optional[str]] = mapped_column(
        String(36),
        Computed("CASE WHEN user_id_a < user_id_b THEN user_id_a ELSE user_id_b END", persisted=False),
    )
    user_max: Mapped[Optional[str]] = mapped_column(
        String(36),
        Computed("CASE WHEN user_id_a < user_id_b THEN user_id_b ELSE user_id_a END", persisted=False),
    )

    __table_args__ = (
        UniqueConstraint("user_min", "user_max", name="uq_friendship_pair"),
    )


class SharedPlant(Base):
    __tablename__ = "shared_plant"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    owner_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    ended_sharing_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "recipient_user_id", "plant_id", name="uq_shared_triplet"),
    )

    owner_user: Mapped["User"] = relationship(
        foreign_keys=[owner_user_id],
        back_populates="outgoing_shares",
    )
    recipient_user: Mapped["User"] = relationship(
        foreign_keys=[recipient_user_id],
        back_populates="incoming_shares",
    )
    plant: Mapped["Plant"] = relationship(back_populates="shared_records")


# ======================================================================
# WATERING
# ======================================================================

class WateringPlan(Base):
    __tablename__ = "watering_plan"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    next_due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    check_soil_moisture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    __table_args__ = (
        UniqueConstraint("user_id", "plant_id", name="uq_wp_user_plant"),
        Index("idx_wp_due", "next_due_at"),
    )

    user: Mapped["User"] = relationship(back_populates="watering_plans")
    plant: Mapped["Plant"] = relationship(back_populates="watering_plans")


class WateringLog(Base):
    __tablename__ = "watering_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plant.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    done_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped["User"] = relationship(back_populates="watering_logs")
    plant: Mapped["Plant"] = relationship(back_populates="watering_logs")


# ======================================================================
# QUESTIONARIO (1:N – domande personalizzate per utente)
# ======================================================================

class Question(Base):
    __tablename__ = "question"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    options_json: Mapped[Optional[dict]] = mapped_column(MySQLJSON)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_answer: Mapped[Optional[str]] = mapped_column(Text)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="questions")


# ======================================================================
# REMINDER
# ======================================================================

class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    recurrence_rrule: Mapped[Optional[str]] = mapped_column(String(255))
    entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    entity_id: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="reminders")
