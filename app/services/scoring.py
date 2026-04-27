from __future__ import annotations

from dataclasses import dataclass

from app.services.rarity import get_rarity


@dataclass(slots=True)
class ScoreBreakdown:
    score: int
    rarity_tier: str
    rarity_bonus: int
    speed_bonus: int
    zipf: float | None = None


def calculate_score_details(word: str, response_seconds: float) -> ScoreBreakdown:
    rarity = get_rarity(word)
    speed_bonus = max(0, int((17 - response_seconds) // 2))
    length_score = len(word)
    score = int(length_score + speed_bonus + rarity.bonus)
    return ScoreBreakdown(
        score=score,
        rarity_tier=rarity.tier,
        rarity_bonus=rarity.bonus,
        speed_bonus=speed_bonus,
        zipf=rarity.zipf,
    )


def calculate_score(word: str, response_seconds: float) -> int:
    return calculate_score_details(word, response_seconds).score
