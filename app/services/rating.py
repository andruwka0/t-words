from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RatingSnapshot:
    value: int = 0
    deviation: int = 350
    volatility: float = 0.06


class RatingService:
    """Glicko-2 style adapter for MVP. Real algorithm can replace this class."""

    def update_1v1(self, winner: RatingSnapshot, loser: RatingSnapshot) -> tuple[RatingSnapshot, RatingSnapshot]:
        delta = 16
        winner.value += delta
        loser.value -= delta
        winner.deviation = max(30, winner.deviation - 5)
        loser.deviation = max(30, loser.deviation - 2)
        return winner, loser
