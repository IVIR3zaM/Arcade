import subprocess

from shared.models import Game


def build_command(game: Game) -> list[str]:
    """Build the command that launches a game, without running it."""
    if game.emulator == "duckstation":
        return ["duckstation", game.rom_path]
    return ["retroarch", "-L", game.core, game.rom_path]


def run_game(command: list[str]) -> None:
    """Run a launch command and wait for the emulator to exit."""
    subprocess.run(command)
