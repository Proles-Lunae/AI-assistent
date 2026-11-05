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
    # What the assistant calls you, e.g. "Good morning, sir." Empty = "sir".
    name: str = "sir"

    def address(self) -> str:
        return self.name.strip() or "sir"


@dataclass
class WeatherSettings:
    city: str = ""  # Empty = detect your location automatically.
    units: str = "metric"  # "metric" (°C, km/h) or "imperial" (°F, mph)


@dataclass
class VoiceSettings:
    # Microsoft neural voices: en-GB-SoniaNeural, en-GB-LibbyNeural, en-GB-MaisieNeural
    voice: str = "en-GB-SoniaNeural"
    rate: str = "+0%"  # Speaking speed, e.g. "-10%" or "+15%"


@dataclass
class ClapSettings:
    # Microphone: "" = Windows' default, or a number / part of a name
    # from: python -m assistant --devices
    device: str = ""
    # Loudness (0.0-1.0) a sound must reach to count as a clap.
    # Find a good value with: python -m assistant --levels
    threshold: float = 0.2
    # A clap must also be this many times louder than the background noise...
    noise_ratio: float = 5.0
    # ...and this many times louder than a moment before (claps are sudden).
    onset_ratio: float = 3.0
    # Allowed time between the two claps, in seconds.
    min_gap: float = 0.15
    max_gap: float = 0.9
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
        key = key.lower()
        if key not in known:
            # Warn rather than crash, so old config files keep working.
            print(f"(Ignoring unknown setting '{key}' in config.toml)")
            continue
        current = getattr(section, key)
        # Allow ints in the file where floats are expected (e.g. cooldown = 3).
        if isinstance(current, float) and isinstance(value, int):
            value = float(value)
        elif isinstance(current, str) and not isinstance(value, str):
            value = str(value)
        setattr(section, key, value)


class ConfigError(ValueError):
    pass


def load_config(path: Path | None = None, report: bool = False) -> Config:
    """Load settings from a TOML file, falling back to defaults.

    With ``report``, says which file was used, so it's obvious when your
    settings aren't being picked up.
    """
    config = Config()
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        if report:
            print(f"No settings file found at {path}, using the default settings.")
            hidden_txt = path.with_name(path.name + ".txt")
            if hidden_txt.exists():
                print(
                    f"  Found {hidden_txt.name} instead: Windows added '.txt' to the name. "
                    f"Rename it with:  ren {hidden_txt.name} {path.name}"
                )
        return config
    # "utf-8-sig" also accepts the invisible marker (BOM) some editors add.
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"There's a mistake in {path}: {exc}.\n"
            'Text values need quotes, e.g.  name = "sir"  and  city = "Berlin"'
        ) from exc
    for section_name, values in data.items():
        section = getattr(config, section_name.lower(), None)
        if section is None or not isinstance(values, dict):
            print(f"(Ignoring unknown section [{section_name}] in config.toml)")
            continue
        _apply(section, values)
    if report:
        print(f"Settings loaded from {path}")
    return config
