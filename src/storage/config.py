"""
Configuration management for the storage layer.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class StorageConfig(BaseSettings):
    """Configuration for database connectivity.

    Expects environment variables like DATABASE_URL.
    """

    database_url: str = Field(
        default="postgresql+asyncpg://aegis_user:aegis_secure_pass_2026@localhost:5432/aegis_db",
        description="PostgreSQL connection string (asyncpg)",
        validation_alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=20, description="Database connection pool size")
    db_max_overflow: int = Field(default=10, description="Maximum overflow connections")
    db_echo: bool = Field(default=False, description="Whether to echo SQL queries (for debugging)")

    model_config = {
        "env_prefix": "AEGIS_",  # Usually DB settings might not have AEGIS_ prefix if we use standard DATABASE_URL, let's configure field aliases or remove prefix.
        "case_sensitive": False,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Initialize a global config instance
storage_config = StorageConfig()
