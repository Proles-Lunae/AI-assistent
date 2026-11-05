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


def clap(rng, loudness=0.8):
    block = quiet(rng)
    decay = np.exp(-np.arange(300) / 40.0)
    block[100:400] += (rng.uniform(-1, 1, 300) * loudness * decay).astype(np.float32)
    return block


def tone(i, loudness=0.5, ramp_blocks=6):
    """A steady sound (like a voice or music) that fades in over a few blocks."""
    t = (np.arange(BLOCK) + i * BLOCK) / RATE
    level = loudness * min(1.0, (i + 1) / ramp_blocks)
    return (np.sin(2 * np.pi * 220 * t) * level).astype(np.float32)


def run(pattern, settings=None, clap_loudness=0.8, noise=None):
    """Feed blocks: 'c' clap, '.' silence, 't' steady sound. Return trigger times."""
    rng = np.random.default_rng(0)
    detector = DoubleClapDetector(settings or ClapSettings())
    triggers = []
    tone_blocks = 0
    for i, ch in enumerate(pattern):
        if ch == "c":
            block = clap(rng, clap_loudness)
        elif ch == "t":
            block = tone(tone_blocks)
            tone_blocks += 1
        else:
            block = quiet(rng)
        if noise:
            block = block + rng.normal(0, noise, BLOCK).astype(np.float32)
        now = i * BLOCK_SECONDS
        if detector.process_block(block, now) == "double":
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


def test_quiet_double_clap_triggers():
    # Windows microphones are often set low: a clap may only reach ~0.3.
    assert len(run(gap(1) + "c" + gap(0.35) + "c" + gap(0.5), clap_loudness=0.3)) == 1


def test_double_clap_in_a_noisy_room_triggers():
    assert len(run(gap(1) + "c" + gap(0.35) + "c" + gap(0.5), noise=0.02)) == 1


def test_slow_clapper_triggers():
    assert len(run(gap(1) + "c" + gap(0.75) + "c" + gap(0.5))) == 1


def test_steady_sound_does_not_trigger():
    # Speech or music: loud, but it builds up and keeps going.
    assert run(gap(1) + "t" * 80 + gap(1)) == []


def test_single_clap_reports_single():
    rng = np.random.default_rng(0)
    detector = DoubleClapDetector(ClapSettings())
    results = [detector.process_block(quiet(rng), i * BLOCK_SECONDS) for i in range(40)]
    results.append(detector.process_block(clap(rng), 40 * BLOCK_SECONDS))
    assert results[-1] == "single"
    assert set(results[:-1]) == {None}


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
    assert config.weather.city == ""  # untouched default: detect location


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


WINDOWS_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
    {"name": "Mikrofon (Webcam)", "max_input_channels": 1, "hostapi": 0},
    {"name": "Mikrofon (PD200X Podcast Microp", "max_input_channels": 1, "hostapi": 0},
    {"name": "Lautsprecher (Realtek)", "max_input_channels": 0, "hostapi": 0},
    {"name": "Mikrofon (PD200X Podcast Microphone)", "max_input_channels": 1, "hostapi": 1},
    {"name": "Mikrofon (PD200X Podcast Microphone)", "max_input_channels": 1, "hostapi": 2},
]


def pick(device, default_hostapi=0):
    from assistant.clap_detector import input_device

    return input_device(ClapSettings(device=device), WINDOWS_DEVICES, default_hostapi)


def test_device_by_name_picks_one_entry_on_the_default_audio_system():
    assert pick("PD200X") == 2
    assert pick("pd200x", default_hostapi=2) == 5  # case doesn't matter


def test_device_by_number_and_default():
    assert pick("2") == 2
    assert pick("") is None


def test_unknown_device_explains_how_to_list():
    import pytest

    with pytest.raises(ValueError, match="--devices"):
        pick("Blue Yeti")


def test_speakers_are_not_picked_as_microphone():
    import pytest

    with pytest.raises(ValueError):
        pick("Realtek")


def test_weather_summary_is_one_sentence():
    report = WeatherReport("Berlin", "light rain", 11.2, 9.0, 13.0, 7.5, 80, 15.0, "°C", "km/h")
    text = report.summary()
    assert text.count(".") == 1 and text.endswith(".")
    assert "Berlin" in text and "80 percent" in text


def test_weather_numbers_are_rounded_for_claude():
    report = WeatherReport("Berlin", "fog", 11.4, 9.6, 13.0, 7.5, 0, 15.2, "°C", "km/h")
    data = report.as_dict()
    assert (data["temperature"], data["feels_like"], data["low"]) == (11, 10, 8)


def test_first_sentence_keeps_only_one():
    from assistant.brain import first_sentence

    assert first_sentence("Rainy, high of 13. Take an umbrella!") == "Rainy, high of 13."
    assert first_sentence("Low of 7.5 degrees today.") == "Low of 7.5 degrees today."


def test_detect_location_from_ipinfo(monkeypatch):
    from assistant import weather

    monkeypatch.setattr(weather, "_get_json", lambda url, params: {"loc": "52.52,13.40", "city": "Berlin"})
    assert weather.detect_location() == (52.52, 13.40, "Berlin")


def test_detect_location_falls_back_to_second_service(monkeypatch):
    from assistant import weather

    def fake(url, params):
        if "ipinfo" in url:
            raise ConnectionError("blocked")
        return {"latitude": 48.14, "longitude": 11.58, "city": "Munich"}

    monkeypatch.setattr(weather, "_get_json", fake)
    assert weather.detect_location() == (48.14, 11.58, "Munich")


def test_empty_city_uses_detected_location(monkeypatch):
    from assistant import weather

    calls = []
    monkeypatch.setattr(weather, "detect_location", lambda: calls.append("auto") or (1.0, 2.0, "Here"))
    monkeypatch.setattr(weather, "find_city", lambda c: calls.append(c) or (1.0, 2.0, c))
    forecast = {
        "current": {"temperature_2m": 5, "apparent_temperature": 3, "weather_code": 3, "wind_speed_10m": 9},
        "daily": {"temperature_2m_max": [7], "temperature_2m_min": [1], "precipitation_probability_max": [20]},
    }
    monkeypatch.setattr(weather, "_get_json", lambda url, params: forecast)
    assert weather.get_weather("").city == "Here"
    assert weather.get_weather("Hamburg").city == "Hamburg"
    assert calls == ["auto", "Hamburg"]
