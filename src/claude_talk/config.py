"""Configuration loading from env files."""

import os
from pathlib import Path


class Config:
    """Loads config from defaults.env + ~/.claude-talk/config.env"""

    def __init__(self, project_dir: Path | None = None, user_config_dir: Path | None = None):
        self.values: dict[str, str] = {}
        if project_dir is None:
            project_dir = Path(__file__).parent.parent.parent
        self._load_env_file(project_dir / "config/defaults.env")
        if user_config_dir is None:
            user_config_dir = Path.home() / ".claude-talk"
        user_config = user_config_dir / "config.env"
        if user_config.exists():
            self._load_env_file(user_config)

    def _load_env_file(self, path: Path):
        """Parse shell-style KEY=VALUE lines"""
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            # Remove quotes
            val = val.strip().strip('"').strip("'")
            self.values[key.strip()] = val

        # Second pass: expand variables now that all are loaded
        for key in list(self.values.keys()):
            original = self.values[key]
            # Expand $HOME and ${VAR} using both os.environ and self.values
            expanded = original
            for var_key, var_val in self.values.items():
                expanded = expanded.replace(f"${{{var_key}}}", var_val)
                expanded = expanded.replace(f"${var_key}", var_val)
            expanded = os.path.expandvars(expanded)
            self.values[key] = expanded

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, str(default)))
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key, "").lower()
        if val in ("true", "1", "yes"):
            return True
        if val in ("false", "0", "no"):
            return False
        return default
