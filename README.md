# Clap-activated voice assistant

Clap twice and the assistant wakes up. It greets you in a British female voice
and tells you the temperature outside: "Good evening, sir. It's 8 degrees."

- **Wake word:** two claps, picked up by your microphone.
- **Voice:** Microsoft's free "Sonia" neural voice (British English, female), via `edge-tts`.
- **Weather:** [Open-Meteo](https://open-meteo.com/), which is free and needs no API key.
- **Brain:** Claude, through your **Claude Code login** (`assistant/brain.py`).
  The greeting doesn't need it, so it's currently unused and kept ready for future
  features. It runs the `claude` command, so no API key is needed.

## Setup

You need **Python 3.11 or newer**, a microphone and speakers.
[Claude Code](https://code.claude.com/docs), installed and logged in, is only
needed for future features that use Claude.

1. Get the code:

   ```bash
   git clone https://github.com/Proles-Lunae/AI-assistent.git
   cd AI-assistent
   ```

2. Create a virtual environment and install the packages.

   **Windows (Command Prompt):**

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

   If `py` isn't found, install Python from https://www.python.org/downloads/ and
   tick **"Add python.exe to PATH"** during setup.

   **Mac / Linux:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   On Linux you may also need PortAudio for the microphone:
   `sudo apt install libportaudio2`.

3. Make sure Claude Code is logged in. Run `claude` once and follow the login steps.

4. Optional: copy `config.example.toml` to `config.toml` to change settings. She
   calls you "sir" by default; set `name` under `[user]` to change that. The
   weather is for your location, worked out automatically from your internet
   connection (roughly your city; with a VPN on, the VPN's location). To use a
   specific place instead, set `city` under `[weather]`, e.g. `city = "Berlin"`.

## Running it

| Command | What it does |
| --- | --- |
| `python -m assistant` | Listen for a double clap and greet you each time |
| `python -m assistant --now` | Greet you once right away, without clapping |
| `python -m assistant --say "Hello there"` | Speak some text, to test the voice |
| `python -m assistant --levels` | Show microphone loudness, to tune clap detection |
| `python -m assistant --devices` | List the microphones |

Press **Ctrl+C** to stop.

## Tuning the clap detection

While it's listening, each clap it hears prints `clap heard (loudness 0.45)`.
If you clap and nothing prints at all, it isn't hearing you:

1. Run `python -m assistant --levels`, stay quiet a moment, then clap a few times.
   Each line shows how loud the microphone is, and `CLAP` / `DOUBLE CLAP` show what
   the detector makes of it. At the end it suggests a `threshold` if your claps
   were too quiet.
2. If the levels stay at `0.00`, the microphone is sending silence. On Windows go
   to **Settings > Privacy & security > Microphone** and turn on both
   "Microphone access" and "Let desktop apps access your microphone".
3. If the wrong microphone is used, run `python -m assistant --devices` and put
   the number (or part of the name) as `device` under `[clap]` in `config.toml`.

## How it works

```
microphone.py ──► clap_detector.py ──two claps──┬─► greeting (recorded at start-up) ─┐
                                                └─► weather.py: temperature right now ─┴─► voice.py ─► speakers
```

| File | Job |
| --- | --- |
| `assistant/microphone.py` | Chooses the microphone, records from it, and runs `--levels` and `--devices` |
| `assistant/clap_detector.py` | Spots short, sharp sounds and checks the gap between two of them |
| `assistant/timeframes.py` | The three time frames and their standard greetings, in one table |
| `assistant/weather.py` | Finds your location (or city), gets the current temperature and the chance of rain |
| `assistant/brain.py` | Talks to Claude (unused for now, kept for future features) |
| `assistant/voice.py` | Turns text into speech and plays it |
| `assistant/main.py` | Ties everything together and handles the command options |
| `assistant/config.py` | Default settings, and loading `config.toml` |

**Greetings and time frames:** the day has three time frames, each with its own
standard greeting:

| Time frame | Greeting |
| --- | --- |
| 3am – 11am | Good morning |
| 11am – 6pm | Good afternoon |
| 6pm – 3am | Good evening |

**What she says:** the greeting, then the temperature, checked fresh at every
clap. The chance of rain is added only when it's over 20% for the rest of the
time frame: "Good evening, sir. It's 8 degrees, with a 70 percent chance of rain
this evening."

**Why there's no wait:** the three greetings are recorded when the program starts.
When you clap, the greeting plays straight away, and while she says it (about a
second and a half) the temperature is checked and the rest of the sentence is
recorded. It follows right after the greeting, with the silence between the two
recordings trimmed so they sound like one sentence. Your location is looked up at
start-up and remembered for 3 hours.

If the weather can't be reached, she says so after the greeting. If the online
voice can't be reached, it falls back to your computer's own voices (`pyttsx3`).

## Tests

```bash
pip install pytest
pytest
```
