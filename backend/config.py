from pydantic_settings import BaseSettings
import os
from functools import lru_cache

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/financial_agent")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379")
    
    # Google OAuth settings
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("BACKEND_URL", "http://localhost:8000") + "/auth/google/callback"
    
    # Hubspot OAuth settings
    hubspot_client_id: str = os.getenv("HUBSPOT_CLIENT_ID", "")
    hubspot_client_secret: str = os.getenv("HUBSPOT_CLIENT_SECRET", "")
    hubspot_redirect_uri: str = os.getenv("BACKEND_URL", "http://localhost:8000") + "/auth/hubspot/callback"
    
    # OpenAI settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    
    # App settings
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings() 