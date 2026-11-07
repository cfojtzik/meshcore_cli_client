"""Configuration manager for MeshCore TUI client."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".config" / "meshcore"
CONFIG_FILE = CONFIG_DIR / "tui_config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "port": "/dev/ttyUSB0",
    "baudrate": 115200,
    "timeout": 10,
    "simulation_mode": False,
    "auto_sync_clock": False,
    "refresh_interval": 5,
}


class Config:
    def __init__(self, config_file: Optional[Path] = CONFIG_FILE) -> None:
        self.config_file = config_file
        self.data: Dict[str, Any] = DEFAULT_CONFIG.copy()
        if self.config_file:
            self.load()

    def load(self) -> None:
        try:
            if self.config_file and self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.data.update(loaded)
        except Exception:
            # Fallback to defaults on error
            pass

    def save(self) -> None:
        try:
            if self.config_file:
                self.config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
        except Exception:
            pass

    @property
    def port(self) -> str:
        return str(self.data.get("port", "/dev/ttyUSB0"))

    @port.setter
    def port(self, val: str) -> None:
        self.data["port"] = val
        self.save()

    @property
    def baudrate(self) -> int:
        return int(self.data.get("baudrate", 115200))

    @baudrate.setter
    def baudrate(self, val: int) -> None:
        self.data["baudrate"] = val
        self.save()

    @property
    def timeout(self) -> int:
        return int(self.data.get("timeout", 10))

    @timeout.setter
    def timeout(self, val: int) -> None:
        self.data["timeout"] = val
        self.save()

    @property
    def simulation_mode(self) -> bool:
        return bool(self.data.get("simulation_mode", False))

    @simulation_mode.setter
    def simulation_mode(self, val: bool) -> None:
        self.data["simulation_mode"] = val
        self.save()

    @property
    def refresh_interval(self) -> int:
        try:
            value = int(self.data.get("refresh_interval", 5))
        except (TypeError, ValueError, OverflowError):
            value = 5
        return max(1, min(300, value))

    @refresh_interval.setter
    def refresh_interval(self, val: int) -> None:
        self.data["refresh_interval"] = val
        self.save()
