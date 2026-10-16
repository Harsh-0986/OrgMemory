"""Application configuration, loaded from environment / `.env`.

Every knob the agent uses for bounded execution lives here so that limits are
auditable in one place rather than scattered through node functions.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Reads from the process environment and a local `.env` file.  No secrets are
    ever given a default value - a missing key must fail loudly at startup
    rather than silently producing a half-working agent.
    """

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Application ------------------------------------------------------
    app_name: str = "OrgMemory"
    environment: str = "development"
    log_level: str = "INFO"
    # `NoDecode` stops pydantic-settings running `json.loads` on this before
    # the validator below. Without it, a plain `CORS_ORIGINS=http://localhost:3000`
    # dies on the colon, which is exactly what `.env.example` tells people to write.
    #
    # Both `localhost` and `127.0.0.1` are allowed by default. They are
    # distinct origins to a browser, and a developer who opens the second one
    # would otherwise get a silently non-functional dashboard.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # -- FalkorDB ---------------------------------------------------------
    # Both naming conventions are accepted. `FALKOR_DB_INSTANCE` /
    # `FALKOR_DB_PASS` are the variable names the FalkorDB Cloud dashboard
    # hands you; the `FALKORDB_*` names match the Docker/local deployment.
    # Supporting both means a `.env` copied straight from either source works.
    falkordb_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("FALKORDB_HOST", "FALKOR_DB_INSTANCE"),
    )
    falkordb_port: int = 6379
    # FalkorDB Cloud's default user is `falkordb`, not Redis' `default`.
    falkordb_username: str = "falkordb"
    falkordb_password: str = Field(
        default="",
        validation_alias=AliasChoices("FALKORDB_PASSWORD", "FALKOR_DB_PASS"),
    )
    falkordb_graph: str = "orgmemory"
    falkordb_tls: bool = False

    # -- LLM (NVIDIA NIM, OpenAI-compatible) ------------------------------
    # An explicit off-switch. With this false the agent still runs end to end
    # using its deterministic writer, so the demo never depends on a metered
    # endpoint being reachable.
    llm_enabled: bool = True

    # Which provider to use: `nvidia`, `google`, or `auto` to take whichever
    # key happens to be present.
    llm_provider: str = "auto"

    # -- NVIDIA NIM (OpenAI-compatible) ----------------------------------
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "z-ai/glm-5.3-flash"
    nvidia_temperature: float = 0.0
    nvidia_max_tokens: int = 2048

    # -- Google Gemini (official langchain-google-genai client) -----------
    google_api_key: str = ""
    google_model: str = "gemini-3.8-flash"

    # -- Agent execution limits ------------------------------------------
    agent_max_steps: int = Field(default=8, ge=1, le=50)
    # Sized to let the primary demo complete its full query set. The bound still
    # exists to stop a confused agent looping, not to cripple a real run - at 12
    # the demo exhausted the budget and skipped most of its own queries.
    agent_max_tool_calls: int = Field(default=24, ge=1, le=100)
    agent_max_recursion: int = Field(default=25, ge=5, le=200)
    agent_query_timeout_seconds: float = Field(default=15.0, gt=0)

    # -- Graph traversal limits ------------------------------------------
    graph_max_dependency_depth: int = Field(default=3, ge=1, le=6)
    graph_max_results: int = Field(default=100, ge=1, le=1000)

    # -- Derived helpers --------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept either a JSON list or a comma-separated string."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_configured(self) -> bool:
        """True when both the graph and the LLM have credentials available."""
        return bool(
            self.falkordb_host
            and self.falkordb_password
            and (self.nvidia_api_key or self.google_api_key)
        )

    @property
    def missing_settings(self) -> list[str]:
        """Human-readable list of required settings that are not configured."""
        missing: list[str] = []
        if not self.falkordb_password:
            missing.append("FALKORDB_PASSWORD")
        if not self.falkordb_host:
            missing.append("FALKORDB_HOST")
        if not (self.nvidia_api_key or self.google_api_key):
            missing.append("NVIDIA_API_KEY or GOOGLE_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()