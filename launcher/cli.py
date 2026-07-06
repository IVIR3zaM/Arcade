from shared.models import Game


def format_menu(games: list[Game]) -> str:
    """Render games as a numbered menu with console labels."""
    lines = [
        f"{number}. {game.title} ({game.console})"
        for number, game in enumerate(games, start=1)
    ]
    return "\n".join(lines)
