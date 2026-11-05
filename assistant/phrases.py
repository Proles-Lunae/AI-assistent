"""Everything she says, in each language she speaks.

To change her wording, edit the text here. The language is chosen with
``language`` under ``[user]`` in config.toml ("de" or "en").
"""

from __future__ import annotations

INF = float("inf")


class Phrases:
    """The English texts; other languages override what differs."""

    code = "en"
    name = "English"
    voice = "en-GB-SoniaNeural"  # Microsoft neural voice used for this language
    greetings = {"morning": "Good morning", "afternoon": "Good afternoon",
                 "evening": "Good evening"}
    this_period = {"morning": "this morning", "afternoon": "this afternoon",
                   "evening": "this evening"}
    no_weather = "I'm afraid I can't reach the weather service at the moment."
    didnt_catch = "Sorry, I didn't catch that."
    no_brain = "I'm sorry, I can't think straight at the moment. Please try again later."
    goodbye = "Very well. Just clap if you need me."
    # Saying one of these (on its own, or in a short sentence) ends the conversation.
    goodbye_words = ("thank you", "thanks", "goodbye", "bye", "that's all", "that is all",
                     "nothing", "no thanks", "stop", "never mind", "go to sleep",
                     "that's enough", "that will be all", "that'll be all", "you can go")
    # Tips by temperature in °C: the first line whose limit the temperature is
    # at or below is used.
    tips = (
        (0, "It's freezing, so wrap up warm and mind the ice."),
        (7, "A warm coat would be a good idea."),
        (14, "A jacket should do."),
        (22, "A light jumper should be plenty."),
        (28, "It's warm, so dress lightly."),
        (INF, "It's hot, so drink plenty of water and stay in the shade."),
    )
    # What to take along with the umbrella when it's likely to rain.
    rain_extras = ((7, " and a warm coat"), (14, " and a jacket"))
    # Tells Claude which language to answer in.
    claude_instruction = "Answer in English."
    # An example of how you talk to her, which helps the speech recognition.
    whisper_prompt = "Hello. What time is it? What's the weather like today?"
    # A pause after one of these words means you're probably not finished yet.
    unfinished_words = ("and", "or", "but", "because", "so", "that", "if", "when", "um", "uh",
                        "er", "erm", "the", "a", "an", "to", "of", "with", "for", "in", "on",
                        "like", "is", "my", "your", "about", "than")

    # The window: title, what the orb's caption says in each state, tray menu.
    app_title = "Assistant"
    status = {"starting": "Getting ready…", "waiting": "Clap twice to wake me",
              "listening": "Listening…", "thinking": "Thinking…", "speaking": "Speaking…",
              "problem": "Something's wrong – see below"}
    show_window = "Show"
    quit_app = "Quit"
    tray_hint = "I'm still here, next to the clock. Clap twice whenever you need me."

    def greeting(self, period: str, address: str) -> str:
        return self.greetings[period] + (f", {address}" if address else "") + "."

    def temperature(self, t: int) -> str:
        minus = "minus " if t < 0 else ""
        return f"It's {minus}{abs(t)} degree{'' if abs(t) == 1 else 's'} outside."

    def rain(self, chance: int, period: str, extra: str) -> str:
        article = "an" if str(chance).startswith("8") else "a"  # an 80, an 85
        return (f"There's {article} {chance} percent chance of rain {self.this_period[period]}, "
                f"so take an umbrella{extra}.")


class German(Phrases):
    code = "de"
    name = "German"
    voice = "de-DE-KatjaNeural"  # or de-DE-AmalaNeural, de-DE-SeraphinaMultilingualNeural
    greetings = {"morning": "Guten Morgen", "afternoon": "Guten Tag", "evening": "Guten Abend"}
    this_period = {"morning": "heute Morgen", "afternoon": "heute Nachmittag",
                   "evening": "heute Abend"}
    no_weather = "Leider kann ich den Wetterdienst gerade nicht erreichen."
    didnt_catch = "Entschuldigung, das habe ich nicht verstanden."
    no_brain = ("Entschuldigung, ich kann gerade nicht klar denken. "
                "Bitte versuchen Sie es später noch einmal.")
    goodbye = "Sehr wohl. Klatschen Sie einfach, wenn Sie mich brauchen."
    goodbye_words = ("danke", "danke schön", "dankeschön", "vielen dank", "tschüss", "tschüs",
                     "auf wiedersehen", "stopp", "stop", "das war's", "das wars",
                     "das ist alles", "das war alles", "das reicht", "nichts", "schon gut",
                     "gute nacht", "geh schlafen", "ende", "aufhören", "hör auf")
    tips = (
        (0, "Es friert, also ziehen Sie sich warm an und passen Sie auf Glätte auf."),
        (7, "Ein warmer Mantel wäre eine gute Idee."),
        (14, "Eine Jacke sollte reichen."),
        (22, "Ein leichter Pullover sollte genügen."),
        (28, "Es ist warm, also kleiden Sie sich leicht."),
        (INF, "Es ist heiß, also trinken Sie viel Wasser und bleiben Sie im Schatten."),
    )
    rain_extras = ((7, " und einen warmen Mantel"), (14, " und eine Jacke"))
    claude_instruction = ("Answer in German, addressing the user politely with 'Sie'. "
                          "Write 'Grad' and 'Prozent' as words.")
    whisper_prompt = "Hallo. Wie spät ist es? Wie wird das Wetter heute?"
    app_title = "Assistentin"
    status = {"starting": "Wird gestartet…", "waiting": "Zweimal klatschen, um mich zu wecken",
              "listening": "Ich höre zu…", "thinking": "Ich denke nach…",
              "speaking": "Ich spreche…", "problem": "Etwas stimmt nicht – siehe unten"}
    show_window = "Anzeigen"
    quit_app = "Beenden"
    tray_hint = ("Ich bin weiter da, unten neben der Uhr. Klatschen Sie zweimal, "
                 "wenn Sie mich brauchen.")
    unfinished_words = ("und", "oder", "aber", "weil", "dass", "denn", "wenn", "ob", "also",
                        "äh", "ähm", "öh", "hm", "mit", "von", "zu", "für", "der", "die", "das",
                        "den", "dem", "des", "ein", "eine", "einen", "einem", "in", "im", "auf",
                        "an", "am", "wie", "als", "mein", "meine", "über", "nach", "bei")

    def greeting(self, period: str, address: str) -> str:
        # German capitalises the form of address: "Guten Abend, Sir."
        return super().greeting(period, address[:1].upper() + address[1:])

    def temperature(self, t: int) -> str:
        minus = "minus " if t < 0 else ""
        if abs(t) == 1:
            return f"Es ist {minus}ein Grad draußen."
        return f"Es sind {minus}{abs(t)} Grad draußen."

    def rain(self, chance: int, period: str, extra: str) -> str:
        return (f"Die Regenwahrscheinlichkeit liegt {self.this_period[period]} bei {chance} "
                f"Prozent, also nehmen Sie einen Regenschirm{extra} mit.")


LANGUAGES = {p.code: p() for p in (Phrases, German)}


def phrases_for(language: str) -> Phrases:
    """The phrases for a language code such as "de"; unknown codes get English."""
    code = (language or "").strip().lower()[:2]
    if code not in LANGUAGES:
        print(f"(No phrases for language '{language}'; using English. Available: "
              f"{', '.join(LANGUAGES)})")
        return LANGUAGES["en"]
    return LANGUAGES[code]


def all_goodbye_words() -> set[str]:
    """Goodbye words of every language, so either language ends a conversation."""
    return {w for p in LANGUAGES.values() for w in p.goodbye_words}
