"""Runtime settings — override via environment variables prefixed TG_."""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# visualization/ directory (two levels up from this file)
_VIZ_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic: str = "vehicle/+/#"
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    live_hz: float = 20.0
    rolling_buffer_max_frames: int = 5000
    live_recordings_dir: str = os.path.join(_VIZ_DIR, "output", "live_recordings")
    tamper_api_url: str = "http://localhost:8001"

    model_config = SettingsConfigDict(env_prefix="TG_", env_file=".env", extra="ignore")


settings = Settings()
