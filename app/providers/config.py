"""Provider configuration — stored locally in a JSON file.

Keeps API keys and tokens out of the database.
"""

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "provider_config.json"


def _load() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def get_provider_config(provider: str) -> dict[str, Any]:
    config = _load()
    return config.get(provider, {})


def save_provider_config(provider: str, data: dict[str, Any]):
    config = _load()
    config[provider] = data
    _save(config)


def delete_provider_config(provider: str):
    config = _load()
    config.pop(provider, None)
    _save(config)


def list_configured_providers() -> list[str]:
    return list(_load().keys())
