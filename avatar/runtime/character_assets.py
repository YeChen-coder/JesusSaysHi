"""Bind all visual assets to one identity before loading the visual model."""
from dataclasses import dataclass
from pathlib import Path
import os
from characters import select_character


@dataclass(frozen=True)
class CharacterAssets:
    name: str
    metadata: dict

    @property
    def key(self):
        return self.name.lower()

    def path(self, field):
        value = self.metadata.get(field)
        return Path('/work') / value if value else None

    @property
    def renderer(self):
        return self.metadata['renderer']

    @property
    def settings(self):
        return self.metadata['settings']

    @property
    def checkpoint(self):
        return self.path('checkpoint')

    @property
    def base(self):
        return self.path('base')

    @property
    def teeth(self):
        return self.path('teeth')

    @property
    def detail(self):
        return self.path('detail')

    @property
    def image(self):
        return self.path('image')

    @property
    def landmarks(self):
        return self.path('landmarks')


def character_assets():
    selection = select_character(os.getenv('FEATHERTALK_CHARACTER', 'QinChe'))
    return CharacterAssets(selection['name'], selection)
