from dataclasses import dataclass


@dataclass
class Game:
    title: str
    console: str
    emulator: str
    core: str
    rom_path: str
    cover_path: str
