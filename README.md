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

4. Optional: copy `config.example.toml` to `config.toml` and set your name and city.

## Running it

| Command | What it does |
| --- | --- |
| `python -m assistant` | Listen for a double clap and greet you each time |
| `python -m assistant --now` | Greet you once right away, without clapping |
| `python -m assistant --say "Hello there"` | Speak some text, to test the voice |
| `python -m assistant --levels` | Show microphone loudness, to tune clap detection |

Press **Ctrl+C** to stop.

## Tuning the clap detection

If claps are missed, or other noises set it off, run `python -m assistant --levels`
and clap a few times. Each clap shows as a number between 0 and 1. In `config.toml`,
set `threshold` under `[clap]` a bit below your typical clap and above everyday
noise like talking or typing.

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
| `assistant/weather.py` | Finds your city and fetches the current weather and today's forecast |
| `assistant/brain.py` | Asks Claude for a short spoken greeting and weather briefing |
| `assistant/voice.py` | Turns text into speech and plays it |
| `assistant/main.py` | Ties everything together and handles the command options |
| `assistant/config.py` | Default settings, and loading `config.toml` |

If Claude can't be reached, the assistant still greets you with a simple built-in
message. If the online voice can't be reached, it falls back to your computer's
own voices (`pyttsx3`).

## Tests

```bash
pip install pytest
pytest
```
