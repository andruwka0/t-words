from __future__ import annotations

import re
import random
from dataclasses import dataclass
from typing import Callable


@dataclass
class BotProfile:
    name: str
    delay_ms: tuple[int, int]
    fail_probability: float
    preferred_length: int
    rare_letter_bias: float


BOTS = {
    'easy': BotProfile('EasyBot', (1200, 2600), 0.22, 5, 0.1),
    'medium': BotProfile('MediumBot', (700, 1900), 0.12, 7, 0.2),
    'hard': BotProfile('HardBot', (350, 1200), 0.05, 9, 0.35),
    'Poet': BotProfile('Poet', (600, 1400), 0.1, 8, 0.45),
    'Scientist': BotProfile('Scientist', (550, 1300), 0.08, 10, 0.3),
    'Trickster': BotProfile('Trickster', (400, 1000), 0.2, 6, 0.5),
}


class BotService:
    def __init__(self, words: list[str]) -> None:
        self.words = words

    def pick_word(
        self,
        letter: str,
        used: set[str],
        profile: BotProfile,
        word_pool: list[str] | None = None,
        avoid_word: str | None = None,
        used_lemmas: set[str] | None = None,
        normalize: Callable[[str], str] | None = None,
    ) -> str | None:
        pool = word_pool or self.words
        options = [w for w in pool if w.startswith(letter) and w not in used and re.fullmatch(r'[а-яё]{2,}', w)]
        if used_lemmas and normalize is not None:
            options = [w for w in options if normalize(w) not in used_lemmas]
        if profile.name == 'EasyBot':
            short_options = [w for w in options if len(w) <= 6]
            if short_options:
                options = short_options
        if avoid_word and avoid_word in options and len(options) > 1:
            options = [w for w in options if w != avoid_word]
        if not options:
            return None

        def weight(word: str) -> float:
            length_fit = 1 / (1 + abs(len(word) - profile.preferred_length))
            rare_bonus = 1 + (profile.rare_letter_bias * sum(c in 'яэщфцю' for c in word))
            return length_fit * rare_bonus

        return random.choices(options, weights=[weight(w) for w in options], k=1)[0]
