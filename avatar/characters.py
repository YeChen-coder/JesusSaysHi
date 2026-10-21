"""Resolve the avatar character from characters.json (the container passes FEATHERTALK_CHARACTER)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def select_character(value=None, root=ROOT):
    catalog = json.loads((root / 'characters.json').read_text(encoding='utf-8'))
    value = value or catalog['default']
    for name, character in catalog['characters'].items():
        if name.lower() == value.strip().lower():
            return dict(character, name=name)
    raise ValueError(f"Unknown character {value!r}; characters.json has {', '.join(catalog['characters'])}")


if __name__ == '__main__':
    print(json.dumps(select_character()))
