from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from .env import resolve_llm_settings
from .profile import SellerProfile, load_profile


@dataclass(slots=True)
class AgentConfig:
    provider: str = "local"
    base_url: str = "http://10.0.30.33:8080/v1"
    model: str = "qwen3.6-27b-mtp"
    api_key: str = "local"
    timeout_s: float = 120.0
    temperature: float = 0.7
    enable_thinking: bool = True
    thinking_budget: int | None = None
    profile: SellerProfile = field(default_factory=SellerProfile)

    @property
    def seller_name(self) -> str:
        return self.profile.seller_name

    @classmethod
    def from_env(cls, profile_path: str | None = None, *, env_file: str = ".env") -> AgentConfig:
        profile = load_profile(profile_path)
        env_seller_name = os.getenv("AGENT_SELLER_NAME")
        if env_seller_name:
            profile = replace(profile, seller_name=env_seller_name)

        llm = resolve_llm_settings(env_file)
        return cls(
            provider=str(llm["provider"]),
            base_url=str(llm["base_url"]),
            model=str(llm["model"]),
            api_key=str(llm["api_key"]),
            timeout_s=float(os.getenv("OPENAI_TIMEOUT_S", "120")),
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
            enable_thinking=bool(llm["enable_thinking"]),
            thinking_budget=int(os.environ["OPENAI_THINKING_BUDGET"])
            if os.getenv("OPENAI_THINKING_BUDGET")
            else None,
            profile=profile,
        )
