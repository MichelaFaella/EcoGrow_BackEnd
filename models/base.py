from typing import Dict
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import MetaData, create_engine
from utils.config import settings

NAMING_CONVENTION: Dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

engine = create_engine(settings.DB_URI, echo=settings.DB_ECHO, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
