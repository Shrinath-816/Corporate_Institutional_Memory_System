"""
Module: config/settings.py

Purpose:
    Centralized configuration management for the Institutional Memory System.

Responsibilities:
    - Load and validate all environment variables using Pydantic BaseSettings.
    - Provide a single source of truth for all configuration values across the system.
    - Enforce type safety and validation on all configuration parameters.

Workflow:
    1. On application startup, Settings class is instantiated.
    2. Pydantic reads values from environment variables or .env file.
    3. All modules import the singleton `settings` object for configuration access.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional


class GeminiSettings(BaseSettings):
    """Configuration for Google Gemini LLM API."""

    api_key: str = Field(..., env="GOOGLE_API_KEY", description="Google Gemini API key")
    model: str = Field(
        default="gemini-2.5-flash",
        env="GEMINI_MODEL",
        description="Gemini model identifier"
    )
    temperature: float = Field(
        default=0.2,
        env="GEMINI_TEMPERATURE",
        description="LLM sampling temperature (lower = more deterministic)"
    )
    max_tokens: int = Field(
        default=8192,
        env="GEMINI_MAX_TOKENS",
        description="Maximum tokens in LLM response"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class ChromaDBSettings(BaseSettings):
    """Configuration for ChromaDB vector store."""

    persist_directory: str = Field(
        default="./chroma_db",
        env="CHROMA_PERSIST_DIR",
        description="Local directory where ChromaDB persists data"
    )
    collection_name: str = Field(
        default="institutional_memory",
        env="CHROMA_COLLECTION_NAME",
        description="Default ChromaDB collection name"
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        env="EMBEDDING_MODEL",
        description="SentenceTransformer model used for generating embeddings"
    )
    top_k_results: int = Field(
        default=5,
        env="CHROMA_TOP_K",
        description="Number of top results to retrieve from vector search"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class Neo4jSettings(BaseSettings):
    """Configuration for Neo4j graph database."""

    uri: str = Field(
        default="bolt://localhost:7687",
        env="NEO4J_URI",
        description="Neo4j connection URI"
    )
    username: str = Field(
        default="neo4j",
        env="NEO4J_USERNAME",
        description="Neo4j authentication username"
    )
    password: str = Field(
        default="password",
        env="NEO4J_PASSWORD",
        description="Neo4j authentication password"
    )
    database: str = Field(
        default="neo4j",
        env="NEO4J_DATABASE",
        description="Neo4j target database name"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class DataSettings(BaseSettings):
    """Configuration for data ingestion and storage paths."""

    raw_data_path: str = Field(
        default="./data/raw/emails.csv",
        env="RAW_DATA_PATH",
        description="Path to raw Enron email CSV file"
    )
    processed_data_path: str = Field(
        default="./data/processed/emails_clean.csv",
        env="PROCESSED_DATA_PATH",
        description="Path to cleaned and processed email CSV file"
    )
    synthetic_data_dir: str = Field(
        default="./data/synthetic/",
        env="SYNTHETIC_DATA_DIR",
        description="Directory containing synthetic policy and decision data"
    )
    chunk_size: int = Field(
        default=512,
        env="CHUNK_SIZE",
        description="Maximum token size per text chunk for RAG ingestion"
    )
    chunk_overlap: int = Field(
        default=50,
        env="CHUNK_OVERLAP",
        description="Overlap tokens between consecutive chunks to preserve context"
    )
    max_emails_to_ingest: int = Field(
        default=1000,
        env="MAX_EMAILS",
        description="Maximum number of emails to ingest into the system"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class APISettings(BaseSettings):
    """Configuration for FastAPI backend server."""

    host: str = Field(
        default="0.0.0.0",
        env="API_HOST",
        description="Host address for FastAPI server"
    )
    port: int = Field(
        default=8000,
        env="API_PORT",
        description="Port for FastAPI server"
    )
    debug: bool = Field(
        default=False,
        env="API_DEBUG",
        description="Enable FastAPI debug mode"
    )
    api_version: str = Field(
        default="v1",
        env="API_VERSION",
        description="API version prefix for all routes"
    )
    secret_key: str = Field(
        default="change-this-in-production",
        env="SECRET_KEY",
        description="Secret key for JWT token signing"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class LoggingSettings(BaseSettings):
    """Configuration for application-wide logging."""

    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )
    log_format: str = Field(
        default="json",
        env="LOG_FORMAT",
        description="Log output format: json or text"
    )
    log_file: Optional[str] = Field(
        default="./logs/app.log",
        env="LOG_FILE",
        description="Path to log file. If None, logs only to stdout."
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


class Settings(BaseSettings):
    """
    Master settings class aggregating all subsystem configurations.

    This is the single entry point for configuration access across
    the entire Institutional Memory System. All modules should import
    the `settings` singleton defined at the bottom of this file.
    """

    app_name: str = Field(
        default="Institutional Memory System",
        env="APP_NAME",
        description="Application display name"
    )
    environment: str = Field(
        default="development",
        env="ENVIRONMENT",
        description="Deployment environment: development, staging, production"
    )

    # Subsystem configurations
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    chromadb: ChromaDBSettings = Field(default_factory=ChromaDBSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    api: APISettings = Field(default_factory=APISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @validator("environment")
    def validate_environment(cls, value: str) -> str:
        """Validates that environment is one of the allowed values.

        Args:
            value: The environment string to validate.

        Returns:
            Lowercased environment string if valid.

        Raises:
            ValueError: If environment is not development, staging, or production.
        """
        allowed = {"development", "staging", "production"}
        if value.lower() not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got '{value}'")
        return value.lower()

    class Config:
        env_file = ".env"
        extra = "ignore"


# ---------------------------------------------------------------------------
# Singleton instance — import this across all modules
# ---------------------------------------------------------------------------
settings = Settings()