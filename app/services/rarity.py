from __future__ import annotations

from dataclasses import dataclass

try:
    from wordfreq import zipf_frequency
except ModuleNotFoundError:  # pragma: no cover
    zipf_frequency = None


@dataclass(slots=True)
class RarityInfo:
    tier: str
    bonus: int
    zipf: float | None


def get_rarity(word: str) -> RarityInfo:
    normalized = word.lower().strip().replace('ё', 'е')

    if zipf_frequency is None:
        if len(normalized) >= 12:
            return RarityInfo('ultra_rare', 14, None)
        if len(normalized) >= 10:
            return RarityInfo('epic', 10, None)
        if len(normalized) >= 8:
            return RarityInfo('rare', 6, None)
        if len(normalized) >= 6:
            return RarityInfo('uncommon', 2, None)
        return RarityInfo('common', 0, None)

    zipf = float(zipf_frequency(normalized, 'ru'))
    if zipf <= 0:
        if len(normalized) >= 6:
            return RarityInfo('legendary', 18, zipf)
        return RarityInfo('rare', 6, zipf)
    if zipf <= 2.2:
        return RarityInfo('ultra_rare', 14, zipf)
    if zipf <= 3.0:
        return RarityInfo('epic', 10, zipf)
    if zipf <= 3.7:
        return RarityInfo('rare', 6, zipf)
    if zipf <= 4.3:
        return RarityInfo('uncommon', 2, zipf)
    return RarityInfo('common', 0, zipf)
