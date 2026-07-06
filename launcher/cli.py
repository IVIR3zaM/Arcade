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
