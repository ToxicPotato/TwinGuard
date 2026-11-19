"""Report service settings."""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict

_SVC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VIZ_DIR = os.path.dirname(_SVC_DIR)


class Settings(BaseSettings):
    output_dir: str = os.path.join(_SVC_DIR, "output")
    viz_dir: str = _VIZ_DIR  # path to visualization/ for shared python/ modules

    model_config = SettingsConfigDict(env_prefix="TG_REPORT_", env_file=".env", extra="ignore")


settings = Settings()
