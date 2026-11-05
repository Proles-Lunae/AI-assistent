from datetime import datetime
from types import SimpleNamespace

import numpy as np

from assistant.clap_detector import DoubleClapDetector
from assistant.config import ClapSettings, load_config
from assistant.timeframes import frame_end, frame_start, standard_greeting, time_of_day
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
    import urllib.request

    import pytest

    from assistant import weather

    def fail(*args, **kwargs):
        err = ssl.SSLCertVerificationError(1, "certificate verify failed")
        err.verify_message = "certificate has expired"
        raise urllib.error.URLError(err)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
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
    from assistant.microphone import input_device

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


def test_claude_gets_latest_temperature_and_no_high_or_low():
    report = WeatherReport("Berlin", "fog", 11.4, 9.6, 13.0, 7.5, 0, 15.2, "°C", "km/h")
    assert report.spoken_facts() == {
        "city": "Berlin", "conditions": "fog", "temperature": 11, "unit": "°C"}


def test_rain_chance_only_mentioned_above_20_percent():
    def report(rain):
        return WeatherReport("Berlin", "overcast", 8, 6, 10, 5, rain, 18, "°C", "km/h")

    for rain in (0, 15, 20):
        assert "rain_chance_percent" not in report(rain).spoken_facts()
        assert "percent" not in report(rain).summary("evening")
    assert report(21).spoken_facts()["rain_chance_percent"] == 21
    assert "21 percent chance of rain this evening" in report(21).summary("evening")


def test_simple_forecast_wording():
    r = WeatherReport("Berlin", "light rain", 8.4, 6, 10.2, 4.6, 70, 18, "°C", "km/h")
    assert r.summary("evening") == (
        "In Berlin it's 8 degrees and light rain, with a 70 percent chance of rain this evening.")
    assert "high" not in r.summary() and "low" not in r.summary()


def test_prompt_tells_claude_to_skip_unlikely_rain(monkeypatch):
    from assistant.brain import ClaudeBrain
    from assistant.config import BrainSettings

    prompts = []
    brain = ClaudeBrain(BrainSettings())
    monkeypatch.setattr(brain, "ask", lambda prompt: prompts.append(prompt) or "Fine.")
    dry = WeatherReport("Berlin", "clear sky", 8, 6, 10, 5, 10, 18, "°C", "km/h")
    wet = WeatherReport("Berlin", "rain", 8, 6, 10, 5, 80, 18, "°C", "km/h")
    brain.weather_briefing(dry, datetime(2026, 1, 2, 18))
    brain.weather_briefing(wet, datetime(2026, 1, 2, 18))
    assert "do not mention any chance of rain" in prompts[0] and "rain_chance" not in prompts[0]
    assert '"rain_chance_percent": 80' in prompts[1]
    assert all("No high or low" in p for p in prompts)


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


def hourly_forecast(start, hours, temps, codes, rain):
    from datetime import timedelta

    return {
        "time": [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)],
        "temperature_2m": temps,
        "apparent_temperature": [t - 2 for t in temps],
        "weather_code": codes,
        "precipitation_probability": rain,
        "wind_speed_10m": [10] * hours,
    }


def test_empty_city_uses_detected_location(monkeypatch):
    from assistant import weather

    calls = []
    monkeypatch.setattr(weather, "detect_location", lambda: calls.append("auto") or (1.0, 2.0, "Here"))
    monkeypatch.setattr(weather, "find_city", lambda c: calls.append(c) or (1.0, 2.0, c))
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    forecast = {"hourly": hourly_forecast(now, 12, [5] * 12, [3] * 12, [20] * 12)}
    monkeypatch.setattr(weather, "_get_json", lambda url, params: forecast)
    assert weather.get_weather("").city == "Here"
    assert weather.get_weather("Hamburg").city == "Hamburg"
    assert calls == ["auto", "Hamburg"]


def test_forecast_covers_only_the_time_frame():
    from assistant.weather import summarise_hours

    day = datetime(2026, 1, 2, 0)
    # 24 hours: cold and clear at night, warm and rainy 11am-6pm.
    temps = [2] * 11 + [9, 10, 12, 13, 12, 11, 10] + [4] * 6
    codes = [0] * 11 + [61] * 7 + [0] * 6
    rain = [0] * 11 + [80, 90, 70, 60, 50, 40, 30] + [0] * 6
    hourly = hourly_forecast(day, 24, temps, codes, rain)
    afternoon = summarise_hours(hourly, datetime(2026, 1, 2, 11), datetime(2026, 1, 2, 18))
    assert afternoon["description"] == "light rain"
    assert (afternoon["high"], afternoon["low"], afternoon["rain_chance"]) == (13, 9, 90)
    assert afternoon["temperature"] == 9  # at the start of the frame
    evening = summarise_hours(hourly, datetime(2026, 1, 2, 18), datetime(2026, 1, 3, 3))
    assert evening["description"] == "clear sky" and evening["rain_chance"] == 0


def test_she_calls_you_sir_by_default():
    from assistant.config import Config, UserSettings

    assert Config().user.address() == "sir"
    assert UserSettings(name="").address() == "sir"
    assert UserSettings(name="  ").address() == "sir"
    assert standard_greeting("morning", Config().user.address()) == "Good morning, sir."


def test_config_written_by_notepad_with_bom(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b'\xef\xbb\xbf[user]\r\nname = "Luca"\r\n')
    assert load_config(path).user.address() == "Luca"


def test_config_sections_and_keys_ignore_capitals(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[User]\nName = "Luca"\n')
    assert load_config(path).user.address() == "Luca"


def test_config_mistake_gets_a_clear_message(tmp_path):
    import pytest

    from assistant.config import ConfigError

    path = tmp_path / "config.toml"
    path.write_text("[user]\nname = Luca\n")  # missing quotes
    with pytest.raises(ConfigError, match="quotes"):
        load_config(path)


def test_hidden_txt_extension_is_pointed_out(tmp_path, capsys):
    (tmp_path / "config.toml.txt").write_text('[user]\nname = "Luca"\n')
    config = load_config(tmp_path / "config.toml", report=True)
    out = capsys.readouterr().out
    assert "ren config.toml.txt config.toml" in out
    assert config.user.address() == "sir"


def test_startup_says_which_settings_file_is_used(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[user]\nname = "sir"\n')
    load_config(path, report=True)
    assert f"Settings loaded from {path}" in capsys.readouterr().out


def test_location_is_remembered(monkeypatch):
    from assistant import weather

    lookups = []
    monkeypatch.setattr(weather, "_lookup_location", lambda: lookups.append(1) or (1.0, 2.0, "Here"))
    weather.detect_location()
    weather.detect_location()
    assert len(lookups) == 1


def make_assistant(monkeypatch, claude_seconds=0.0):
    """An Assistant with fake weather, Claude and voice; records what it plays."""
    import time as _time

    from assistant import main
    from assistant.config import Config

    report = WeatherReport("Berlin", "light rain", 8, 6, 10, 5, 70, 18, "°C", "km/h")
    monkeypatch.setattr(main, "get_weather", lambda *a: report)
    a = main.Assistant(Config())

    def slow_claude(weather, start):
        _time.sleep(claude_seconds)
        return "Claude's forecast."

    a.brain.weather_briefing = slow_claude
    a.speaker.prepare = lambda text: SimpleNamespace(text=text)
    played = []
    a.speaker.play = lambda speech: played.append(speech.text)
    return a, played


def test_clap_before_claude_is_ready_still_gives_one_message(monkeypatch):
    from assistant.briefing import BriefingCache

    a, played = make_assistant(monkeypatch, claude_seconds=1.0)
    a.cache = BriefingCache(a.build_briefing)
    a.cache.start()
    try:
        a.wake_up()  # straight after starting: Claude still busy
        assert len(played) == 1
        assert played[0].startswith("Good ") and ", sir." in played[0]
        assert "light rain" in played[0]  # the quick forecast, in the same message
    finally:
        a.cache.stop()


def test_clap_after_claude_is_ready_plays_claudes_version(monkeypatch):
    from assistant.briefing import BriefingCache

    a, played = make_assistant(monkeypatch)
    a.cache = BriefingCache(a.build_briefing)
    a.cache.start()
    try:
        a.cache.take(timeout=2)
        a.wake_up()
        assert played == [played[0]] and played[0].endswith("sir. Claude's forecast.")
    finally:
        a.cache.stop()


def test_frame_end():
    assert frame_end(datetime(2026, 1, 2, 3)) == datetime(2026, 1, 2, 11)
    assert frame_end(datetime(2026, 1, 2, 11)) == datetime(2026, 1, 2, 18)
    assert frame_end(datetime(2026, 1, 2, 18)) == datetime(2026, 1, 3, 3)
    # Asked at any time in a frame, also after midnight.
    assert frame_end(datetime(2026, 1, 2, 15, 30)) == datetime(2026, 1, 2, 18)
    assert frame_end(datetime(2026, 1, 3, 1)) == datetime(2026, 1, 3, 3)


def test_pick_british_female_falls_back_in_order():
    us_female = SimpleNamespace(id="us-zira", name="Zira", languages=["en_US"], gender="female")
    gb_male = SimpleNamespace(id="gb-george", name="George", languages=[b"\x05en-gb"])
    us_male = SimpleNamespace(id="us-david", name="David", languages=["en_US"], gender="male")
    assert pick_british_female([us_female, gb_male]) is gb_male  # British beats female
    assert pick_british_female([us_male, us_female]) is us_female
    assert pick_british_female([us_male]) is None
    assert pick_british_female([]) is None


def test_claude_gets_the_prompt_through_stdin_with_the_full_path(monkeypatch):
    from assistant import brain
    from assistant.config import BrainSettings

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="Rainy, high of 13. Umbrella!\n", stderr="")

    monkeypatch.setattr(brain.shutil, "which", lambda c: r"C:\Users\me\claude.cmd")
    monkeypatch.setattr(brain.subprocess, "run", fake_run)
    report = WeatherReport("Berlin", "light rain", 8, 6, 10, 5, 70, 18, "°C", "km/h")
    claude = brain.ClaudeBrain(BrainSettings(model="sonnet"))
    assert claude.weather_briefing(report, datetime(2026, 1, 2, 18)) == "Rainy, high of 13."
    cmd, kwargs = calls[0]
    assert cmd[:2] == [r"C:\Users\me\claude.cmd", "-p"] and cmd[-2:] == ["--model", "sonnet"]
    assert "Good evening" in kwargs["input"] and "18:00 to 03:00" in kwargs["input"]
    assert kwargs["input"] not in cmd  # the prompt is not a command-line argument


def test_briefing_fallbacks(monkeypatch):
    from assistant.brain import BrainError
    from assistant.main import NO_WEATHER

    a, _ = make_assistant(monkeypatch)
    evening = datetime(2026, 1, 2, 18)
    full = a.build_briefing(evening)
    assert full.complete and full.speech.text == "Good evening, sir. Claude's forecast."
    quick = a.build_briefing(evening, quick=True)
    assert not quick.complete and "light rain" in quick.speech.text

    def no_claude(weather, start):
        raise BrainError("offline")

    a.brain.weather_briefing = no_claude
    simple = a.build_briefing(evening)
    assert simple.complete and "8 degrees and light rain" in simple.speech.text

    def no_weather(*args):
        raise ConnectionError("offline")

    from assistant import main

    monkeypatch.setattr(main, "get_weather", no_weather)
    for briefing in (a.build_briefing(evening), a.build_briefing(evening, quick=True)):
        assert not briefing.complete
        assert briefing.speech.text == f"Good evening, sir. {NO_WEATHER}"


def test_config_values_get_the_expected_types(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('[clap]\ndevice = 2\nmin_gap = 1\nsample_rate = 48000\nloudness = 3\n[nope]\n')
    config = load_config(path)
    assert config.clap.device == "2" and config.clap.min_gap == 1.0
    assert isinstance(config.clap.min_gap, float) and config.clap.sample_rate == 48000
    out = capsys.readouterr().out
    assert "unknown setting 'loudness'" in out and "unknown section [nope]" in out


def test_certificate_list_is_loaded_only_once():
    from assistant.weather import ssl_context

    assert ssl_context() is ssl_context()


def test_every_time_frame_has_its_own_greeting():
    assert standard_greeting("afternoon", "sir") == "Good afternoon, sir."
    assert [time_of_day(datetime(2026, 1, 2, h)) for h in (3, 11, 18)] == [
        "morning", "afternoon", "evening"]


def test_unknown_device_is_a_settings_mistake():
    import pytest

    from assistant.config import ConfigError

    with pytest.raises(ConfigError):
        pick("Blue Yeti")


class FakeMicrophone:
    """Stands in for sounddevice: feeds generated blocks to the callback in real time."""

    def __init__(self, blocks=()):
        self.blocks = list(blocks)
        self.default = SimpleNamespace(device=(0, 0), hostapi=0)

    def query_devices(self, device=None, kind=None):
        if device is None and kind is None:
            return WINDOWS_DEVICES
        return {"name": "Fake microphone"}

    def InputStream(self, callback, **settings):
        import threading

        print("(stream opened)")
        blocks, stop = self.blocks, threading.Event()

        def feed():
            for block in blocks:
                if stop.wait(BLOCK_SECONDS):
                    return
                callback(block.reshape(-1, 1), len(block), None, None)

        class Stream:
            def __enter__(self):
                threading.Thread(target=feed, daemon=True).start()
                return self

            def __exit__(self, *exc):
                stop.set()

        return Stream()


def blocks_for(pattern):
    rng = np.random.default_rng(0)
    return [clap(rng) if ch == "c" else quiet(rng) for ch in pattern]


def test_listening_to_the_microphone_wakes_on_a_double_clap(monkeypatch, capsys):
    import sys
    import threading

    from assistant import microphone

    pattern = gap(0.25) + "c" + gap(0.3) + "c" + gap(1)
    monkeypatch.setitem(sys.modules, "sounddevice", FakeMicrophone(blocks_for(pattern)))
    woken = threading.Event()

    class Stop(Exception):
        pass

    def on_double_clap():
        woken.set()
        raise Stop  # stop listening

    def listen():  # on a thread, so a missed double clap fails the test instead of hanging it
        try:
            microphone.listen(ClapSettings(), on_double_clap)
        except Stop:
            pass

    threading.Thread(target=listen, daemon=True).start()
    assert woken.wait(timeout=5)
    out = capsys.readouterr().out
    assert "Using microphone: Fake microphone" in out
    assert out.count("clap heard (loudness ") == 1 and "clap once more..." in out


def test_levels_explains_before_the_microphone_opens(monkeypatch, capsys):
    import sys

    from assistant import microphone

    pattern = gap(0.1) + "c" + gap(0.3) + "c" + gap(5)  # sound for longer than it listens
    monkeypatch.setitem(sys.modules, "sounddevice", FakeMicrophone(blocks_for(pattern)))
    microphone.show_levels(ClapSettings(), seconds=1)
    out = capsys.readouterr().out
    opened = out.index("(stream opened)")
    for line in ("Using microphone: Fake microphone", "Showing loudness", "A clap must reach 0.2"):
        assert out.index(line) < opened
    assert "DOUBLE CLAP" in out and "Loudest sound" in out


def run_main(monkeypatch, *args):
    import sys

    from assistant import main

    monkeypatch.setattr(sys, "argv", ["assistant", *args])
    main.main()  # must not raise: problems are explained in plain words


def test_config_mistake_is_explained_without_a_traceback(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    path.write_text("[user]\nname = Luca\n")
    run_main(monkeypatch, "--config", str(path), "--devices")
    assert "Text values need quotes" in capsys.readouterr().out


def test_unknown_microphone_is_explained_without_a_traceback(tmp_path, monkeypatch, capsys):
    import sys

    path = tmp_path / "config.toml"
    path.write_text('[clap]\ndevice = "Blue Yeti"\n')
    monkeypatch.setitem(sys.modules, "sounddevice", FakeMicrophone())
    run_main(monkeypatch, "--config", str(path), "--levels")
    out = capsys.readouterr().out
    assert "No microphone matches 'Blue Yeti'" in out and "--devices" in out


def test_ctrl_c_while_loading_settings_says_goodbye(monkeypatch, capsys):
    from assistant import main

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "load_config", interrupted)
    run_main(monkeypatch, "--now")
    assert "Goodbye!" in capsys.readouterr().out


STAND_IN_CLAUDE = """\
import json, os, sys
with open(os.environ["STAND_IN_LOG"], "w", encoding="utf-8") as log:
    json.dump({"argv": sys.argv, "stdin": sys.stdin.read()}, log)
if os.environ.get("STAND_IN_FAIL"):
    print("Not logged in", file=sys.stderr)
    sys.exit(1)
print("Mild and dry this evening. Enjoy it!")
"""


def stand_in_claude(tmp_path, monkeypatch):
    """A small script named 'claude' on the PATH, that notes how it was called."""
    import json
    import os
    import sys

    import pytest

    if os.name == "nt":
        pytest.skip("the stand-in is a script with a #! line")
    script = tmp_path / "claude"
    script.write_text(f"#!{sys.executable}\n{STAND_IN_CLAUDE}")
    script.chmod(0o755)
    log = tmp_path / "call.json"
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("STAND_IN_LOG", str(log))
    return script, lambda: json.loads(log.read_text(encoding="utf-8"))


def test_stand_in_claude_gets_the_prompt_through_stdin(tmp_path, monkeypatch):
    from assistant.brain import ClaudeBrain
    from assistant.config import BrainSettings

    script, call = stand_in_claude(tmp_path, monkeypatch)
    report = WeatherReport("Berlin", "fog", 6, 4, 8, 3, 10, 5, "°C", "km/h")
    answer = ClaudeBrain(BrainSettings()).weather_briefing(report, datetime(2026, 1, 2, 18))
    assert answer == "Mild and dry this evening."
    argv, prompt = call()["argv"], call()["stdin"]
    assert argv[0] == str(script)  # the full path, as found by shutil.which
    assert argv[argv.index("--tools") + 1] == ""  # no tools: it only has to talk
    assert "--bare" not in argv and "--model" not in argv  # Claude login, default model
    assert "--strict-mcp-config" in argv and "--disable-slash-commands" in argv
    assert "Good evening" in prompt and '"city": "Berlin"' in prompt and "18:00 to 03:00" in prompt
    assert prompt not in argv  # the prompt is not a command-line argument


def test_stand_in_claude_failing_is_reported(tmp_path, monkeypatch):
    import pytest

    from assistant.brain import BrainError, ClaudeBrain
    from assistant.config import BrainSettings

    stand_in_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("STAND_IN_FAIL", "1")
    with pytest.raises(BrainError, match="exit 1.*Not logged in"):
        ClaudeBrain(BrainSettings()).ask("Hi")


def test_latest_measured_temperature_is_used(monkeypatch):
    from assistant import weather

    monkeypatch.setattr(weather, "detect_location", lambda: (1.0, 2.0, "Here"))
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    forecast = {"hourly": hourly_forecast(now, 12, [5] * 12, [3] * 12, [20] * 12),
                "current": {"temperature_2m": 7.6}}
    monkeypatch.setattr(weather, "_get_json", lambda url, params: forecast)
    assert weather.get_weather("").temperature == 7.6
    del forecast["current"]  # older/odd reply: fall back to the hourly value
    assert weather.get_weather("").temperature == 5
