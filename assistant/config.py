"""Settings for the assistant.

Defaults live here. To change them, copy ``config.example.toml`` to
``config.toml`` in the project folder and edit the values you care about.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass
class UserSettings:
    name: str = ""  # How the assistant addresses you. Empty = no name.


@dataclass
class WeatherSettings:
    city: str = "London"
    units: str = "metric"  # "metric" (°C, km/h) or "imperial" (°F, mph)


@dataclass
class VoiceSettings:
    # Microsoft neural voices: en-GB-SoniaNeural, en-GB-LibbyNeural, en-GB-MaisieNeural
    voice: str = "en-GB-SoniaNeural"
    rate: str = "+0%"  # Speaking speed, e.g. "-10%" or "+15%"


@dataclass
class ClapSettings:
    # Loudness (0.0-1.0) a sound must reach to count as a clap.
    threshold: float = 0.35
    # A clap must also be this many times louder than the background noise.
    noise_ratio: float = 6.0
    # Allowed time between the two claps, in seconds.
    min_gap: float = 0.15
    max_gap: float = 0.8
    # After a double clap, ignore everything for this many seconds.
    cooldown: float = 3.0
    sample_rate: int = 44100
    block_size: int = 1024


@dataclass
class BrainSettings:
    # Path or name of the Claude Code command (uses your Claude login).
    command: str = "claude"
    model: str = ""  # Empty = Claude Code's default model.
    timeout: float = 60.0


@dataclass
class BriefingSettings:
    # Prepare the weather briefing in the background, once per time frame
    # (morning 3am-11am, afternoon 11am-6pm, evening 6pm-3am), so it plays
    # the moment you clap.
    prepare_ahead: bool = True


@dataclass
class Config:
    briefing: BriefingSettings = field(default_factory=BriefingSettings)
    user: UserSettings = field(default_factory=UserSettings)
    weather: WeatherSettings = field(default_factory=WeatherSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    clap: ClapSettings = field(default_factory=ClapSettings)
    brain: BrainSettings = field(default_factory=BrainSettings)


def _apply(section: object, values: dict) -> None:
    known = {f.name: f for f in fields(section)}
    for key, value in values.items():
        if key not in known:
            # Warn rather than crash, so old config files keep working.
            print(f"(Ignoring unknown setting '{key}' in config.toml)")
            continue
        current = getattr(section, key)
        # Allow ints in the file where floats are expected (e.g. cooldown = 3).
        if isinstance(current, float) and isinstance(value, int):
            value = float(value)
        setattr(section, key, value)


def load_config(path: Path | None = None) -> Config:
    """Load settings from a TOML file, falling back to defaults."""
    config = Config()
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return config
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    for section_name, values in data.items():
        if not hasattr(config, section_name):
            raise ValueError(f"Unknown section [{section_name}] in {path}")
        _apply(getattr(config, section_name), values)
    return config
