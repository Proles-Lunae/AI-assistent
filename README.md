# Clap-activated voice assistant

Clap twice and the assistant wakes up. It greets you in a British female voice
and tells you today's weather.

- **Wake word:** two claps, picked up by your microphone.
- **Voice:** Microsoft's free "Sonia" neural voice (British English, female), via `edge-tts`.
- **Weather:** [Open-Meteo](https://open-meteo.com/), which is free and needs no API key.
- **Brain:** Claude, through your **Claude Code login**. The assistant runs the
  `claude` command, so no API key is needed. Usage counts against your Claude plan.

## Setup

You need **Python 3.11 or newer**, a microphone, speakers, and
[Claude Code](https://code.claude.com/docs) installed and logged in.

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
microphone ──► clap_detector.py ──two claps──► weather.py (Open-Meteo)
                                                    │
                                                    ▼
speakers ◄── voice.py (British voice) ◄── brain.py (claude -p, your login)
```

| File | Job |
| --- | --- |
| `assistant/clap_detector.py` | Spots short, sharp sounds and checks the gap between two of them |
| `assistant/weather.py` | Finds your location (or city) and fetches the hourly forecast for a time frame |
| `assistant/brain.py` | Time frames, standard greetings, and asking Claude for the weather briefing |
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

For each time frame, the greeting and a one-sentence forecast for that frame's
hours (for example 6pm–3am for the evening) are made together as **one
recording**, in the background (`assistant/briefing.py`). When you clap, it plays
straight away, with no pause between the greeting and the forecast. Every clap in
the same frame replays it. The next frame's recording is made 30 minutes before
that frame starts, so there's no wait when it changes. That's three Claude
requests a day. Set `prepare_ahead = false` under `[briefing]` to ask Claude on
every clap instead.

If Claude can't be reached, the assistant still gives you a simple built-in
weather report. If the online voice can't be reached, it falls back to your computer's
own voices (`pyttsx3`).

## Tests

```bash
pip install pytest
pytest
```
