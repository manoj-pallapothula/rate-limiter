from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    app_env: str = "development"
    default_limit: int = 100
    default_window_seconds: int = 60

    # Instance identification — useful for distributed setup
    instance_id: str = "instance-1"

    model_config = {"env_file": ".env"}


settings = Settings()