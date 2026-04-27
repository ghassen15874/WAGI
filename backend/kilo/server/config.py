"""App configuration — loads from the backend/.env root."""

import os
from pathlib import Path

from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_backend_dir / ".env", override=True)


class Settings:
    # Default provider
    DEFAULT_PROVIDER: str = os.getenv("DEFAULT_PROVIDER", "groq")
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "llama-3.3-70b-versatile")

    # API Keys
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

    # App URLs
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    BACKEND_PUBLIC_URL: str = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8080")

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_FREE: str = os.getenv("STRIPE_PRICE_FREE", "")
    STRIPE_PRICE_PLUS: str = os.getenv("STRIPE_PRICE_PLUS", "")
    STRIPE_PRICE_PRO: str = os.getenv("STRIPE_PRICE_PRO", "")

    # Session
    SESSION_SECRET: str = os.getenv(
        "SESSION_SECRET",
        os.getenv("JWT_SECRET", "dev-secret-change-in-production-please-use-long-random-string"),
    )

    # GitHub
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_APP_ID: str = os.getenv("GITHUB_APP_ID", "")
    GITHUB_PRIVATE_KEY: str = os.getenv("GITHUB_PRIVATE_KEY", "")
    GITHUB_OAUTH_SCOPE: str = os.getenv("GITHUB_OAUTH_SCOPE", "user:email")
    GITHUB_AUTH_SCOPE: str = os.getenv("GITHUB_AUTH_SCOPE", "user:email")
    GITHUB_DEPLOY_SCOPE: str = os.getenv("GITHUB_DEPLOY_SCOPE", "user:email repo")

    # Scraper gateway
    SCRAPER_URL: str = os.getenv("SCRAPER_URL", "http://localhost:5300")
    SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "")

    # Sandbox
    SANDBOX_BASE_DIR: str = os.getenv(
        "SANDBOX_BASE_DIR",
        str(_backend_dir / "sandbox")
    )
    SANDBOX_DIR: str = SANDBOX_BASE_DIR

    # API Server
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")

    # CORS
    CORS_ORIGINS: list = ["http://localhost:5173", "http://localhost:3000", "http://localhost:5000", "*"]


settings = Settings()
