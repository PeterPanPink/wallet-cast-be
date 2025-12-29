"""Channel configuration schemas for provider-specific settings."""

from pydantic import BaseModel, ConfigDict


class UserConfigs(BaseModel):
    """Container for all provider configurations."""

    model_config = ConfigDict(extra="allow")
    echo_cancellation: bool = True
    noise_suppression: bool = True
    auto_gain_control: bool = False
