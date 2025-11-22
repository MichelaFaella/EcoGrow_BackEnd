import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _float_env(var_name: str, default: float) -> float:
    """Convert env var to float without failing app import."""
    raw = os.getenv(var_name)
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _bool_env(var_name: str, default: bool) -> bool:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", ""}


@dataclass(frozen=True)
class Settings:
    DB_HOST: str = os.getenv("DB_HOST", "db")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "ecogrow")
    DB_PASS: str = os.getenv("DB_PASS", "ecogrow")
    DB_NAME: str = os.getenv("DB_NAME", "ecogrow")
    DB_ECHO: bool = os.getenv("DB_ECHO", "false").lower() == "true"
    
    ECOGROW_MODEL_CACHE: str = os.getenv("ECOGROW_MODEL_CACHE", "artifacts/pretrained")
    ECOGROW_CLIP_PRETRAINED: str = os.getenv("ECOGROW_CLIP_PRETRAINED", "")
    ECOGROW_PAYLOAD_DIR: str = os.getenv("ECOGROW_PAYLOAD_DIR", "artifacts/detectors")
    ECOGROW_SEGMENTATION: bool = _bool_env("ECOGROW_SEGMENTATION", True)
    U2NET_HOME: str = os.getenv("U2NET_HOME", "")

    @property
    def DB_URI(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASS}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )

settings = Settings()
