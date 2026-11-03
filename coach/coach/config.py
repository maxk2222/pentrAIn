from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PENTRAIN_", env_file=".env", extra="ignore")

    backend_url: str = "http://backend:8000"
    backend_ws_url: str = "ws://backend:8000/ws/coach"
    coach_service_token: str = "dev-coach-token"
    llm_timeout_s: int = 300          # per-request timeout — local models
                                      # need headroom on large contexts
    llm_stream: bool = True           # stream draft text to the UI via SSE
    log_level: str = "INFO"


@lru_cache
def get_config() -> Config:
    return Config()
