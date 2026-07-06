from shared.models import Game


def test_game_holds_its_fields():
    game = Game(
        title="Super Mario 64",
        console="N64",
        emulator="retroarch",
        core="mupen64plus_next",
        rom_path="/roms/n64/sm64.z64",
        cover_path="/covers/n64/sm64.png",
    )

    assert game.title == "Super Mario 64"
    assert game.console == "N64"
    assert game.emulator == "retroarch"
    assert game.core == "mupen64plus_next"
    assert game.rom_path == "/roms/n64/sm64.z64"
    assert game.cover_path == "/covers/n64/sm64.png"
