"""Settings for the assistant.

Defaults live here. To change them, copy ``config.example.toml`` to
``config.toml`` in the project folder and edit the values you care about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass
class UserSettings:
    name: str = "sir"  # What she calls you: "Good morning, sir."

    def address(self) -> str:
        return self.name.strip() or "sir"


@dataclass
class WeatherSettings:
    city: str = ""  # Empty = detect your location automatically.
    units: str = "metric"  # "metric" (°C, km/h) or "imperial" (°F, mph)


@dataclass
class VoiceSettings:
    voice: str = "en-GB-SoniaNeural"  # or en-GB-LibbyNeural, en-GB-MaisieNeural
    rate: str = "+0%"  # Speaking speed, e.g. "-10%" or "+15%"


@dataclass
class ClapSettings:
    # Microphone: "" = the default one, or a number / part of a name
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
    command: str = "claude"  # The Claude Code command (uses your Claude login).
    model: str = ""  # Empty = Claude Code's default model.
    timeout: float = 60.0


@dataclass
class Config:
    user: UserSettings = field(default_factory=UserSettings)
    weather: WeatherSettings = field(default_factory=WeatherSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    clap: ClapSettings = field(default_factory=ClapSettings)
    brain: BrainSettings = field(default_factory=BrainSettings)


OBSOLETE_SECTIONS = {"briefing"}  # [briefing] prepare_ahead: greetings are always ready now


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
            hidden = path.with_name(path.name + ".txt")
            if hidden.exists():
                print(
                    f"  Found {hidden.name} instead: Windows added '.txt' to the name. "
                    f"Rename it with:  ren {hidden.name} {path.name}"
                )
        return config
    import tomllib  # here, not at the top: only needed when there's a file to read

    try:
        # "utf-8-sig" also accepts the invisible marker (BOM) some editors add.
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"There's a mistake in {path}: {exc}.\n"
            'Text values need quotes, e.g.  name = "sir"  and  city = "Berlin"'
        ) from exc
    # Unknown names only get a warning, so old config files keep working.
    for section_name, values in data.items():
        if section_name.lower() in OBSOLETE_SECTIONS:
            continue  # settings that no longer exist; older config files still have them
        section = getattr(config, section_name.lower(), None)
        if section is None or not isinstance(values, dict):
            print(f"(Ignoring unknown section [{section_name}] in config.toml)")
            continue
        known = {f.name for f in fields(section)}
        for key, value in values.items():
            key = key.lower()
            if key not in known:
                print(f"(Ignoring unknown setting '{key}' in config.toml)")
                continue
            current = getattr(section, key)
            # Accept e.g. cooldown = 3 for 3.0, and device = 2 for "2".
            if isinstance(current, str) or (isinstance(current, float) and isinstance(value, int)):
                value = type(current)(value)
            setattr(section, key, value)
    if report:
        print(f"Settings loaded from {path}")
    return config
