"""Runtime configuration (env-driven; user-facing settings live in the DB via services/settings.py)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PENTRAIN_", env_file=".env", extra="ignore")

    # data
    database_url: str = "sqlite+aiosqlite:///./pentrain.db"
    content_dir: str = "/content/packs"

    # engine connectivity (bootstrap values; WebGUI settings override per-request)
    engine_mode: str = "nested"  # nested|direct|mock
    pve_url: str = ""            # https://engine:8006
    pve_token_id: str = ""       # user@realm!tokenid
    pve_token_secret: str = ""
    pve_verify_tls: bool = False
    pve_node: str = "pve"
    ludus_url: str = ""          # https://engine:8081
    ludus_api_key: str = ""

    # coach service shared secret (backend <-> coach internal API)
    coach_service_token: str = "dev-coach-token"
    # secret for flag hmac + session tokens; generated at install
    app_secret: str = "dev-secret-change-me"

    cors_origins: str = "*"      # tightened at install
    log_level: str = "INFO"


@lru_cache
def get_config() -> Config:
    return Config()
