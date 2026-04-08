"""
Tests for backend.config.settings.Settings.

Coverage:
- Default field values (isolated from .env via _env_file=None)
- QDRANT_URL computed property
- Required fields validation (missing secrets raise ValidationError)
- Environment variable override via monkeypatch
- SecretStr fields do not leak values in repr
"""

import pytest
from pydantic import ValidationError

from backend.config.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimum env vars required by Settings — excludes optional fields with defaults.
_REQUIRED = {
    "OPENAI_API_KEY": "sk-test-openai",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "PUBMED_API_KEY": "pubmed-test-key",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_pass",
    "POSTGRES_DB": "test_db",
}


_DEFAULTED = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "EXTERNAL_POSTGRES_PORT",
    "REDIS_HOST",
    "REDIS_PORT",
    "EXTERNAL_REDIS_PORT",
    "QDRANT_HOST",
    "QDRANT_PORT",
    "EXTERNAL_QDRANT_PORT",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_LOG_CHANNEL",
    "LLM_COST_THRESHOLD_CHARS",
    "N8N_WEBHOOK_URL",
    "N8N_HEALTH_URL",
    "START_METRICS",
    "METRICS_PORT",
]


def _make(
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, str] | None = None,
    drop: str | None = None,
) -> Settings:
    """
    Build a Settings instance with .env disabled (_env_file=None).
    Sets the minimum required env vars plus any extras, optionally removing one.
    Clears defaulted fields from os.environ so .env values don't bleed through.
    """
    env: dict[str, str] = {**_REQUIRED, **(extra or {})}
    if drop:
        env.pop(drop, None)
        monkeypatch.delenv(drop, raising=False)
    # Remove any defaulted fields not explicitly set, so .env doesn't bleed through
    for key in _DEFAULTED:
        if key not in env:
            monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def s(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with minimum required fields, .env isolated."""
    return _make(monkeypatch)


# ---------------------------------------------------------------------------
# TestSettingsDefaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsDefaults:
    """Default field values are correct when no overrides are present."""

    def test_project_name(self, s: Settings) -> None:
        assert s.PROJECT_NAME == "Seratonin Script"

    def test_version(self, s: Settings) -> None:
        assert s.VERSION == "0.1.0"

    def test_description(self, s: Settings) -> None:
        assert s.DESCRIPTION == "AI Medical Content Generator"

    def test_openai_model(self, s: Settings) -> None:
        assert s.OPENAI_MODEL == "gpt-4o"

    def test_openai_temperature(self, s: Settings) -> None:
        assert s.OPENAI_TEMPERATURE == 0.4

    def test_openai_model_embedding(self, s: Settings) -> None:
        assert s.OPENAI_MODEL_EMBEDDING == "text-embedding-3-small"

    def test_anthropic_model(self, s: Settings) -> None:
        assert s.ANTHROPIC_MODEL == "claude-haiku-4-5"

    def test_anthropic_temperature(self, s: Settings) -> None:
        assert s.ANTHROPIC_TEMPERATURE == 0.4

    def test_postgres_host(self, s: Settings) -> None:
        assert s.POSTGRES_HOST == "postgres"

    def test_postgres_port(self, s: Settings) -> None:
        assert s.POSTGRES_PORT == 5432

    def test_external_postgres_port(self, s: Settings) -> None:
        assert s.EXTERNAL_POSTGRES_PORT == 5433

    def test_redis_host(self, s: Settings) -> None:
        assert s.REDIS_HOST == "redis"

    def test_redis_port(self, s: Settings) -> None:
        assert s.REDIS_PORT == 6379

    def test_external_redis_port(self, s: Settings) -> None:
        assert s.EXTERNAL_REDIS_PORT == 6380

    def test_qdrant_host(self, s: Settings) -> None:
        assert s.QDRANT_HOST == "qdrant"

    def test_qdrant_port(self, s: Settings) -> None:
        assert s.QDRANT_PORT == 6333

    def test_start_metrics_false(self, s: Settings) -> None:
        assert s.START_METRICS is False

    def test_metrics_port(self, s: Settings) -> None:
        assert s.METRICS_PORT == 9000

    def test_slack_bot_token_empty(self, s: Settings) -> None:
        assert s.SLACK_BOT_TOKEN.get_secret_value() == ""

    def test_slack_signing_secret_empty(self, s: Settings) -> None:
        assert s.SLACK_SIGNING_SECRET.get_secret_value() == ""

    def test_slack_log_channel(self, s: Settings) -> None:
        assert s.SLACK_LOG_CHANNEL == "C077Z79HB0V"

    def test_llm_cost_threshold_chars(self, s: Settings) -> None:
        assert s.LLM_COST_THRESHOLD_CHARS == 10000

    def test_n8n_webhook_url(self, s: Settings) -> None:
        assert s.N8N_WEBHOOK_URL == "http://n8n:5678/webhook/publish-post"


# ---------------------------------------------------------------------------
# TestSettingsQdrantURL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsQdrantURL:
    """QDRANT_URL property is computed from QDRANT_HOST and QDRANT_PORT."""

    def test_url_default(self, s: Settings) -> None:
        assert s.QDRANT_URL == "http://qdrant:6333"

    def test_url_custom_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _make(monkeypatch, extra={"QDRANT_HOST": "my-host", "QDRANT_PORT": "7777"})
        assert s.QDRANT_URL == "http://my-host:7777"

    def test_url_uses_http_scheme(self, s: Settings) -> None:
        assert s.QDRANT_URL.startswith("http://")

    def test_url_localhost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _make(
            monkeypatch, extra={"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}
        )
        assert s.QDRANT_URL == "http://localhost:6333"


# ---------------------------------------------------------------------------
# TestSettingsEnvOverride
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsEnvOverride:
    """Explicit env vars override defaults."""

    def test_openai_model_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _make(monkeypatch, extra={"OPENAI_MODEL": "gpt-4-turbo"})
        assert s.OPENAI_MODEL == "gpt-4-turbo"

    def test_postgres_port_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _make(monkeypatch, extra={"POSTGRES_PORT": "5555"})
        assert s.POSTGRES_PORT == 5555

    def test_start_metrics_overridden_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _make(monkeypatch, extra={"START_METRICS": "true"})
        assert s.START_METRICS is True

    def test_required_fields_read_from_env(self, s: Settings) -> None:
        assert s.POSTGRES_USER == "test_user"
        assert s.POSTGRES_PASSWORD == "test_pass"
        assert s.POSTGRES_DB == "test_db"


# ---------------------------------------------------------------------------
# TestSettingsRequiredFields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsRequiredFields:
    """Missing required fields raise ValidationError at instantiation."""

    def test_missing_openai_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="OPENAI_API_KEY")

    def test_missing_anthropic_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="ANTHROPIC_API_KEY")

    def test_missing_pubmed_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="PUBMED_API_KEY")

    def test_missing_postgres_user_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="POSTGRES_USER")

    def test_missing_postgres_password_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="POSTGRES_PASSWORD")

    def test_missing_postgres_db_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValidationError):
            _make(monkeypatch, drop="POSTGRES_DB")


# ---------------------------------------------------------------------------
# TestSettingsSecretStr
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSettingsSecretStr:
    """SecretStr fields must not leak raw values in repr/str."""

    def test_openai_key_masked_in_repr(self, s: Settings) -> None:
        assert "sk-test-openai" not in repr(s)

    def test_openai_key_accessible_via_get_secret_value(self, s: Settings) -> None:
        assert s.OPENAI_API_KEY.get_secret_value() == "sk-test-openai"

    def test_anthropic_key_masked_in_repr(self, s: Settings) -> None:
        assert "sk-ant-test" not in repr(s)

    def test_pubmed_key_accessible(self, s: Settings) -> None:
        assert s.PUBMED_API_KEY.get_secret_value() == "pubmed-test-key"
