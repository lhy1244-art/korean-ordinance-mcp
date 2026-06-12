import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIR / "cache.db"
SAMPLES_DIR = DATA_DIR / "samples"
SEEDS_DIR = DATA_DIR / "seeds"


def _backfill_empty_env_vars() -> None:
    """Fill empty process env vars from .env before Settings() reads them.

    pydantic-settings prefers env vars over the .env file. If a shell sets
    a key like ANTHROPIC_API_KEY to an empty string (Windows occasionally
    pre-populates these), the .env value gets shadowed silently. Treat
    "set but empty" as "unset" by repopulating from .env in that case.
    Real non-empty shell overrides are still respected.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for key, value in dotenv_values(env_path).items():
        if not value:
            continue
        if not os.environ.get(key):  # missing or empty
            os.environ[key] = value


_backfill_empty_env_vars()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model_reasoning: str = "claude-sonnet-4-6"
    anthropic_model_summary: str = "claude-haiku-4-5-20251001"

    congress_gov_api_key: str = ""
    open_states_api_key: str = ""
    govinfo_api_key: str = ""
    # law.go.kr DRF OPEN API: 사용자 ID (sign up at open.law.go.kr).
    # The same OC value works for both 법령(law) and 자치법규(ordin) targets.
    # IP-whitelisted at registration — the machine making the call must
    # match the IP/domain you register.
    law_go_kr_oc: str = ""

    demo_mode: bool = False
    cache_ttl_hours: int = 24

    request_timeout_seconds: float = 15.0
    adapter_concurrency_limit: int = 6


settings = Settings()
