"""Runtime settings loaded from the environment and the project ``.env`` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parent.parent

_PROVIDERS = {"openai", "anthropic", "gemini"}
_CHECKPOINT_BACKENDS = {"redis", "memory"}
_OBSERVABILITY_PROVIDERS = {"langsmith", "phoenix"}


class Settings(BaseSettings):
    """Process settings. Empty environment values fall back to the field default."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    default_max_tokens: int = 2048
    default_temperature: float = 0.0
    gemini_max_tokens: int = 2048
    default_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")

    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    checkpoint_backend: str = Field(default="redis", validation_alias="CHECKPOINT_BACKEND")
    observability_provider: str = Field(
        default="langsmith",
        validation_alias="OBSERVABILITY_PROVIDER",
    )
    langchain_project: str = Field(default="delivery7", validation_alias="LANGCHAIN_PROJECT")
    phoenix_collector_endpoint: str = Field(
        default="http://localhost:6006/v1/traces",
        validation_alias="PHOENIX_COLLECTOR_ENDPOINT",
    )
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    recursion_limit: int = 25
    specialist_recursion_limit: int = 12
    max_supervisor_steps: int = 6
    max_specialist_runs: int = 2
    tavily_max_results: int = 5
    artifact_excerpt_chars: int = 4000
    job_ttl_seconds: int = 86400

    @model_validator(mode="before")
    @classmethod
    def _blank_as_unset(cls, data: object) -> object:
        """Treat blank strings as missing so the field default is used."""
        if not isinstance(data, dict):
            return data
        cleaned: dict[object, object] = {}
        for key, value in data.items():
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    continue
            cleaned[key] = value
        return cleaned

    @field_validator("default_provider", mode="before")
    @classmethod
    def _provider(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        lowered = value.strip().lower()
        if lowered not in _PROVIDERS:
            allowed = ", ".join(sorted(_PROVIDERS))
            raise ValueError(f"LLM_PROVIDER must be one of: {allowed}")
        return lowered

    @field_validator("checkpoint_backend", mode="before")
    @classmethod
    def _checkpoint_backend(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        lowered = value.strip().lower()
        if lowered not in _CHECKPOINT_BACKENDS:
            allowed = ", ".join(sorted(_CHECKPOINT_BACKENDS))
            raise ValueError(f"CHECKPOINT_BACKEND must be one of: {allowed}")
        return lowered

    @field_validator("observability_provider", mode="before")
    @classmethod
    def _observability_provider(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        lowered = value.strip().lower()
        if lowered not in _OBSERVABILITY_PROVIDERS:
            allowed = ", ".join(sorted(_OBSERVABILITY_PROVIDERS))
            raise ValueError(f"OBSERVABILITY_PROVIDER must be one of: {allowed}")
        return lowered

    @field_validator("recursion_limit")
    @classmethod
    def _recursion_floor(cls, value: int) -> int:
        return max(8, value)

    @field_validator("specialist_recursion_limit")
    @classmethod
    def _specialist_recursion_floor(cls, value: int) -> int:
        return max(4, value)

    @field_validator("max_supervisor_steps")
    @classmethod
    def _supervisor_steps_floor(cls, value: int) -> int:
        return max(4, value)

    @field_validator("max_specialist_runs")
    @classmethod
    def _specialist_runs_floor(cls, value: int) -> int:
        return max(1, value)

    @field_validator("tavily_max_results")
    @classmethod
    def _tavily_results_bounds(cls, value: int) -> int:
        return min(10, max(1, value))

    @field_validator("artifact_excerpt_chars")
    @classmethod
    def _excerpt_floor(cls, value: int) -> int:
        return max(200, value)

    @field_validator("job_ttl_seconds")
    @classmethod
    def _job_ttl_floor(cls, value: int) -> int:
        return max(60, value)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()


settings = get_settings()
