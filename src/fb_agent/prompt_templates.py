from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_PROMPTS_PATH = _PACKAGE_DIR / "prompts.yaml"


def default_prompts_path() -> Path:
    return _DEFAULT_PROMPTS_PATH


def resolve_prompts_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_path = os.getenv("FB_AGENT_PROMPTS")
    if env_path:
        return Path(env_path).expanduser()
    return _DEFAULT_PROMPTS_PATH


@lru_cache(maxsize=8)
def _load_prompts_cached(path: str) -> dict[str, Any]:
    prompts_path = Path(path)
    if not prompts_path.exists():
        raise FileNotFoundError(f"Prompt templates not found: {prompts_path}")
    raw = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Prompt templates must be a YAML mapping: {prompts_path}")
    return raw


def load_prompts(path: str | Path | None = None) -> dict[str, Any]:
    return _load_prompts_cached(str(resolve_prompts_path(path)))


def _lookup(data: dict[str, Any], key_path: str) -> str:
    node: Any = data
    for part in key_path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"Prompt template not found: {key_path}")
        node = node[part]
    if not isinstance(node, str):
        raise TypeError(f"Prompt template {key_path!r} must be a string")
    return node.strip()


def render_prompt(key_path: str, /, *, prompts_path: str | Path | None = None, **kwargs: Any) -> str:
    template = _lookup(load_prompts(prompts_path), key_path)
    if kwargs:
        return template.format(**kwargs)
    return template
