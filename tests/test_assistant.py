from datetime import datetime
from types import SimpleNamespace

import numpy as np

from assistant.brain import frame_start, standard_greeting, time_of_day
from assistant.clap_detector import DoubleClapDetector
from assistant.config import ClapSettings, load_config
from assistant.voice import pick_british_female
from assistant.weather import WeatherReport

BLOCK = 1024
RATE = 44100
BLOCK_SECONDS = BLOCK / RATE


def quiet(rng):
    return rng.normal(0, 0.005, BLOCK).astype(np.float32)


def clap(rng):
    block = quiet(rng)
    decay = np.exp(-np.arange(300) / 40.0)
    block[100:400] += (rng.uniform(-1, 1, 300) * 0.8 * decay).astype(np.float32)
    return block


def run(pattern, settings=None):
    """Feed a pattern of 'c' (clap) and '.' (silence) blocks; return trigger times."""
    rng = np.random.default_rng(0)
    detector = DoubleClapDetector(settings or ClapSettings())
    triggers = []
    for i, ch in enumerate(pattern):
        block = clap(rng) if ch == "c" else quiet(rng)
        now = i * BLOCK_SECONDS
        if detector.process_block(block, now):
            triggers.append(now)
    return triggers


def gap(seconds):
    return "." * round(seconds / BLOCK_SECONDS)


def test_double_clap_triggers():
    assert len(run(gap(1) + "c" + gap(0.35) + "c" + gap(0.5))) == 1


def test_single_clap_does_not_trigger():
    assert run(gap(1) + "c" + gap(2)) == []


def test_claps_too_far_apart_do_not_trigger():
    assert run(gap(1) + "c" + gap(1.5) + "c" + gap(1)) == []


def test_silence_does_not_trigger():
    assert run(gap(5)) == []


def test_cooldown_blocks_immediate_retrigger():
    pattern = gap(1) + "c" + gap(0.3) + "c" + gap(0.5) + "c" + gap(0.3) + "c"
    assert len(run(pattern)) == 1


def test_triggers_again_after_cooldown():
    pair = "c" + gap(0.3) + "c"
    assert len(run(gap(1) + pair + gap(4) + pair + gap(0.5))) == 2


def test_time_frames():
    day = lambda h, m=0: datetime(2026, 1, 1, h, m)
    assert time_of_day(day(3)) == "morning"
    assert time_of_day(day(10, 59)) == "morning"
    assert time_of_day(day(11)) == "afternoon"
    assert time_of_day(day(17, 59)) == "afternoon"
    assert time_of_day(day(18)) == "evening"
    assert time_of_day(day(0, 30)) == "evening"
    assert time_of_day(day(2, 59)) == "evening"


def test_frame_start():
    assert frame_start(datetime(2026, 1, 2, 9, 30)) == datetime(2026, 1, 2, 3)
    assert frame_start(datetime(2026, 1, 2, 15)) == datetime(2026, 1, 2, 11)
    assert frame_start(datetime(2026, 1, 2, 21)) == datetime(2026, 1, 2, 18)
    # After midnight the evening is the one that started yesterday.
    assert frame_start(datetime(2026, 1, 2, 1)) == datetime(2026, 1, 1, 18)


def test_standard_greeting():
    assert standard_greeting("morning") == "Good morning."
    assert standard_greeting("evening", "Luca") == "Good evening, Luca."


def test_weather_summary():
    report = WeatherReport("London", "light rain", 11.2, 9.0, 13.0, 7.5, 80, 15.0, "°C", "km/h")
    text = report.summary()
    assert "light rain" in text and "80 percent" in text


def test_pick_british_female_prefers_british_female():
    voices = [
        SimpleNamespace(id="us-david", name="David", languages=["en_US"], gender="male"),
        SimpleNamespace(id="gb-george", name="George", languages=["en_GB"], gender="male"),
        SimpleNamespace(id="gb-hazel", name="Hazel", languages=["en_GB"], gender="female"),
    ]
    assert pick_british_female(voices).id == "gb-hazel"


def test_load_config_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[user]\nname = "Luca"\n[clap]\ncooldown = 5\n'
                    '[briefing]\nrefresh_minutes = 20\n')  # old setting: ignored
    config = load_config(path)
    assert config.user.name == "Luca"
    assert config.clap.cooldown == 5.0
    assert config.weather.city == "London"  # untouched default


def test_weather_uses_certifi_certificates():
    import certifi

    from assistant.weather import ssl_context

    context = ssl_context()
    assert context.verify_mode.name == "CERT_REQUIRED"
    assert context.cert_store_stats()["x509_ca"] > 50  # loaded certifi's list
    assert certifi.where()


def test_certificate_error_gets_a_clear_message(monkeypatch):
    import ssl
    import urllib.error

    import pytest

    from assistant import weather

    def fail(*args, **kwargs):
        err = ssl.SSLCertVerificationError(1, "certificate verify failed")
        err.verify_message = "certificate has expired"
        raise urllib.error.URLError(err)

    monkeypatch.setattr(weather.urllib.request, "urlopen", fail)
    with pytest.raises(ConnectionError, match="date and time"):
        weather.find_city("London")
