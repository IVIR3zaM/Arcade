from collections.abc import Callable

from launcher.emulator import build_command, run_game
from launcher.library import SEED_GAMES
from shared.models import Game


def format_menu(games: list[Game]) -> str:
    """Render games as a numbered menu with console labels."""
    lines = [
        f"{number}. {game.title} ({game.console})"
        for number, game in enumerate(games, start=1)
    ]
    return "\n".join(lines)


def parse_selection(text: str, count: int) -> int | None:
    """Map a 1-based menu choice to a 0-based index, or None if invalid."""
    if not text.strip().isdigit():
        return None
    number = int(text)
    if 1 <= number <= count:
        return number - 1
    return None


def run(
    games: list[Game],
    read_line: Callable[[], str],
    launch: Callable[[Game], None],
    write: Callable[[str], None] = print,
) -> None:
    """Show the menu, launch the chosen game, and repeat until the user quits."""
    while True:
        write(format_menu(games))
        choice = read_line()
        if choice.strip().lower() == "q":
            return
        index = parse_selection(choice, len(games))
        if index is None:
            write("Invalid selection.")
            continue
        launch(games[index])


def launch_game(game: Game) -> None:
    """Build the launch command for a game and run it."""
    run_game(build_command(game))


def main() -> None:
    run(SEED_GAMES, read_line=input, launch=launch_game)


if __name__ == "__main__":
    main()
