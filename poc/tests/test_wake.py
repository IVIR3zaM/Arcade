"""The wake phrase: fuzzy against whisper's creative spellings, and it splits
off the command spoken in the same breath."""

from brain.wake import split_wake


def test_wake_word_alone():
    for heard in ("Hey Arc", "hey arc!", "Hey Ark.", "Hey Arg", "Hallo Arc", "Arc?"):
        woke, rest = split_wake(heard)
        assert woke, heard
        assert rest == ""


def test_wake_word_with_command_in_one_breath():
    woke, rest = split_wake("Hey Arc, stop the game")
    assert woke
    assert rest == "stop the game"


def test_normal_chatter_does_not_wake():
    for heard in (
        "nice shot, your turn",
        "das war knapp!",
        "let's play pong",  # a command WITHOUT the wake word stays ignored when idle
        "",
    ):
        assert split_wake(heard) == (False, ""), heard
