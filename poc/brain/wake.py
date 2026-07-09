"""Wake-word detection on the transcript: "Hey Arc".

The real cabinet listens continuously but only *acts* when addressed. Whisper
mishears the wake phrase in creative ways ("Hey Ark", "Hey Arg", "Hallo Arc"),
so matching is fuzzy over the first words of the transcript. Pure and testable.
"""

import difflib
import re

_WAKE = "hey arc"
# Exact spellings whisper commonly produces for "Hey Arc" in EN and DE.
_VARIANTS = {
    "hey arc",
    "hey ark",
    "hey arg",
    "hey art",
    "hey ach",
    "hey arch",
    "hi arc",
    "hi ark",
    "hallo arc",
    "hallo ark",
    "he arc",
    "hey ак",
    "هی آرک",  # whisper writes Farsi speech in Arabic script
    "های آرک",
    "هی ارک",
}
# How similar the first two words must be to "hey arc" to count as the wake phrase.
_RATIO = 0.72


def split_wake(text: str) -> tuple[bool, str]:
    """Does `text` start with the wake phrase? Returns (woke, remainder).

    The remainder is the rest of the utterance ("hey arc let's play pong" →
    "let s play pong" normalized), so one breath can wake AND command.
    """
    norm = re.sub(r"[^\w\s']", " ", text.lower())
    words = norm.split()
    if not words:
        return False, ""
    prefix2 = " ".join(words[:2])
    if (
        prefix2 in _VARIANTS
        or difflib.SequenceMatcher(None, prefix2, _WAKE).ratio() >= _RATIO
    ):
        return True, " ".join(words[2:])
    # Just the name also works: "Arc, stop the game."
    if words[0] in {"arc", "ark", "arg", "آرک", "ارک"}:
        return True, " ".join(words[1:])
    return False, ""
