from __future__ import annotations

from fb_marketplace.env import load_env_file


def facebook_credentials_from_env(path: str = ".env") -> tuple[None, None]:
    return None, None


__all__ = ["facebook_credentials_from_env", "load_env_file"]
