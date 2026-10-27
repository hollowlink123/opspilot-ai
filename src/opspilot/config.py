"""Validated configuration; credentials are never included in representations."""
import os

from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    api_key: SecretStr | None = None
    model: str = ""
    max_upload_bytes: int = Field(default=1048576, ge=1, le=10485760)
    max_steps: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=40)
    max_context_chars: int = Field(default=60000, ge=1000, le=500000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)

    max_api_requests: int = Field(default=7, ge=1, le=21)
    max_investigation_seconds: int = Field(default=90, ge=1, le=300)

    @classmethod
    def from_env(cls) -> "Settings":
        values = {name: os.environ[f"OPSPILOT_{name.upper()}"]
                  for name in cls.model_fields
                  if f"OPSPILOT_{name.upper()}" in os.environ}
        values.update(api_key=os.getenv("GEMINI_API_KEY") or None,
                      model=os.getenv("GEMINI_MODEL", ""))
        return cls(**values)
