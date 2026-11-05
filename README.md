# Clap-activated voice assistant

Clap twice and the assistant wakes up. She greets you, tells you the temperature
outside with a useful tip, and then answers your questions. She speaks **German**
by default (or English):
"Guten Abend, Sir. Es sind 8 Grad draußen. Eine Jacke sollte reichen."

- **Wake word:** two claps, picked up by your microphone.
- **Voice:** Microsoft's free neural voices via `edge-tts`: "Katja" (German, female),
  or "Sonia" (British English, female) when she speaks English.
- **Weather:** [Open-Meteo](https://open-meteo.com/), which is free and needs no API key.
- **Hearing you:** after the greeting she listens, and turns what you say into text
  with [Whisper](https://github.com/SYSTRAN/faster-whisper), on your own PC.
- **Brain:** Claude answers your questions, through your **Claude Code login**
  (`assistant/brain.py`). It runs the `claude` command, so no API key is needed;
  usage counts against your Claude plan.

## Setup

You need **Python 3.11 or newer**, a microphone, speakers, and
[Claude Code](https://code.claude.com/docs) installed and logged in (for answering
your questions). The first time she listens, the speech recognition downloads its
model (about 460 MB).

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
| `python -m assistant --talk` | Talk to her right away, without clapping |

Press **Ctrl+C** to stop.

## Language

Set `language` under `[user]` in `config.toml`: `"de"` for German (the default) or
`"en"` for English. That switches everything at once: the greeting, the
temperature and tips, the voice, the speech recognition and Claude's answers. In
German she addresses you politely with "Sie". All her sentences are in
`assistant/phrases.py`, one section per language, so the wording is easy to change.

## Talking to her

After the greeting you hear a short **beep**: she's listening. Ask your question
normally; she notices when you've stopped (about a second of quiet), and answers
after a few seconds of thinking. Then she beeps again for a follow-up question,
and remembers what you talked about. Take as long as you like between questions:
she keeps listening until you **tell her to stop**, by saying "stop", "goodbye",
"thanks", "that's all" or "go to sleep". Then she goes back to waiting for claps.

Settings are under `[listen]` in `config.toml`:

- If she doesn't notice you talking, lower `min_level` (e.g. to `0.003`).
- If she cuts you off mid-sentence, raise `silence_seconds` (e.g. to `1.5`).
- For even better recognition, set `model = "medium"` (slower, 1.5 GB download);
  for speed, `"base"` or `"tiny"`.
- To have her also stop when you've been quiet a while, set `end_after_quiet`
  to a number of seconds (e.g. `30`).
- To turn listening off, set `enabled = false`.

She can't look things up on the internet, so she answers from Claude's own
knowledge (plus today's date, time and your town).

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
                                                                                                    │ beep
you ──► microphone.py ──► listening.py (Whisper: speech to text) ──► brain.py (Claude) ──► voice.py ◄┘
```

| File | Job |
| --- | --- |
| `assistant/microphone.py` | Chooses the microphone, records from it, and runs `--levels` and `--devices` |
| `assistant/clap_detector.py` | Spots short, sharp sounds and checks the gap between two of them |
| `assistant/timeframes.py` | The three time frames and their standard greetings, in one table |
| `assistant/weather.py` | Finds your location (or city), gets the current temperature and the chance of rain |
| `assistant/phrases.py` | Everything she says, in German and English |
| `assistant/listening.py` | Records your question until you stop talking, and turns it into text (Whisper) |
| `assistant/brain.py` | Asks Claude to answer your question, remembering the conversation |
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

**What she says:** the greeting, the temperature (checked fresh at every clap),
and a tip for the weather (shown here in English; the German ones mean the same):

| Weather | Tip |
| --- | --- |
| Chance of rain over 20% | "There's a 70 percent chance of rain this evening, so take an umbrella" (and a warm coat / jacket when it's cold) |
| 0° or below | "It's freezing, so wrap up warm and mind the ice." |
| up to 7° | "A warm coat would be a good idea." |
| up to 14° | "A jacket should do." |
| up to 22° | "A light jumper should be plenty." |
| up to 28° | "It's warm, so dress lightly." |
| above 28° | "It's hot, so drink plenty of water and stay in the shade." |

To change the wording or the temperatures, edit `tips` and `rain_extras` in
`assistant/phrases.py` (there's one set per language).

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
