from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_PROFILE_PATH = _PACKAGE_DIR / "agent.yaml"


@dataclass(slots=True)
class SellerProfile:
    seller_name: str = "Dennis"
    pickup_location: str | None = None
    first_discount_pct: float = 5.0
    max_discount_pct: float = 10.0

    def __post_init__(self) -> None:
        if self.first_discount_pct <= 0:
            raise ValueError("first_discount_pct must be greater than 0")
        if self.max_discount_pct <= 0:
            raise ValueError("max_discount_pct must be greater than 0")
        if self.first_discount_pct >= self.max_discount_pct:
            raise ValueError("first_discount_pct must be less than max_discount_pct")


def default_profile_path() -> Path:
    return _DEFAULT_PROFILE_PATH


def resolve_profile_path(path: str | Path | None = None) -> Path | None:
    if path is not None:
        return Path(path).expanduser()
    env_path = os.getenv("FB_AGENT_PROFILE")
    if env_path:
        return Path(env_path).expanduser()
    if _DEFAULT_PROFILE_PATH.exists():
        return _DEFAULT_PROFILE_PATH
    return None


def load_profile(path: str | Path | None = None) -> SellerProfile:
    profile_path = resolve_profile_path(path)
    if profile_path is None:
        return SellerProfile()

    if not profile_path.exists():
        raise FileNotFoundError(f"Agent profile not found: {profile_path}")

    raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if raw is None:
        return SellerProfile()
    if not isinstance(raw, dict):
        raise ValueError(f"Agent profile must be a YAML mapping: {profile_path}")

    return SellerProfile(**_profile_kwargs(raw))


def _profile_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    negotiation = raw.get("negotiation") or {}
    if not isinstance(negotiation, dict):
        raise ValueError("negotiation must be a YAML mapping")

    kwargs: dict[str, Any] = {}
    if "seller_name" in raw:
        kwargs["seller_name"] = str(raw["seller_name"])
    if "pickup_location" in raw:
        value = raw["pickup_location"]
        kwargs["pickup_location"] = None if value is None else str(value)
    if "first_discount_pct" in negotiation:
        kwargs["first_discount_pct"] = float(negotiation["first_discount_pct"])
    if "max_discount_pct" in negotiation:
        kwargs["max_discount_pct"] = float(negotiation["max_discount_pct"])
    return kwargs
