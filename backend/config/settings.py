from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    PROJECT_NAME: str = "Seratonin Script"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "AI Medical Content Generator"

    # LLM / AI
    LLM_COST_THRESHOLD_CHARS: int = 10000
    OPENAI_API_KEY: SecretStr = Field(default=...)
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.4
    OPENAI_MODEL_EMBEDDING: str = "text-embedding-3-small"
    OPENAI_TRANSLATION_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: SecretStr = Field(default=...)
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    # ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_TEMPERATURE: float = 0.4
    # ANTHROPIC_TRANSLATION_MODEL: str = "claude-haiku-4-5"

    # external API client
    PUBMED_API_KEY: SecretStr = Field(default=...)
    PUBMED_API_URL: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    PUBMED_WEB_URL: str = "https://pubmed.ncbi.nlm.nih.gov"
    CLINICAL_PUBLICATION_TYPES: str = (
        "Review[pt] OR Systematic Review[pt] OR "
        "Practice Guideline[pt] OR Guideline[pt] OR "
        "Clinical Trial[pt] OR Meta-Analysis[pt]"
    )
    # Database
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    EXTERNAL_POSTGRES_PORT: int = 5433

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    EXTERNAL_REDIS_PORT: int = 6380

    # Qdrant
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    EXTERNAL_QDRANT_PORT: int = 6333
    # Slack
    SLACK_BOT_TOKEN: SecretStr = Field(default=SecretStr(""))
    SLACK_SIGNING_SECRET: SecretStr = Field(default=SecretStr(""))
    # n8n
    N8N_WEBHOOK_URL: str = "http://127.0.0.1:5678/webhook/publish-post"
    # Pydantic configuration
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
