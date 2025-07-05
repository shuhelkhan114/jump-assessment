from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:password@localhost:5432/financial_agent"
    
    # Authentication
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Google OAuth
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    
    # HubSpot OAuth
    hubspot_client_id: Optional[str] = None
    hubspot_client_secret: Optional[str] = None
    hubspot_redirect_uri: str = "http://localhost:8000/auth/hubspot/callback"
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    # Frontend URL
    frontend_url: str = "http://localhost:3000"
    
    # Redis (for Celery)
    redis_url: str = "redis://redis:6379"
    
    # Application settings
    app_name: str = "Financial Agent"
    debug: bool = True
    
    # Gmail settings
    gmail_batch_size: int = 100
    gmail_max_results: int = 1000
    
    # HubSpot settings
    hubspot_batch_size: int = 100
    
    # Vector search settings
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    similarity_threshold: float = 0.7
    max_search_results: int = 10
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# Global settings instance
_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings 