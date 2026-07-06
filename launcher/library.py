from shared.models import Game

# A small hardcoded library to prove the CLI end-to-end before a real DB exists.
SEED_GAMES: list[Game] = [
    Game(
        title="Super Mario 64",
        console="N64",
        emulator="retroarch",
        core="mupen64plus_next",
        rom_path="/roms/n64/sm64.z64",
        cover_path="/covers/n64/sm64.png",
    ),
    Game(
        title="Sonic the Hedgehog",
        console="Genesis",
        emulator="retroarch",
        core="genesis_plus_gx",
        rom_path="/roms/genesis/sonic.md",
        cover_path="/covers/genesis/sonic.png",
    ),
    Game(
        title="Crash Bandicoot",
        console="PS1",
        emulator="duckstation",
        core=None,
        rom_path="/roms/ps1/crash.chd",
        cover_path="/covers/ps1/crash.png",
    ),
]
