from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

try:
    import pymorphy3 as _pymorphy
except ModuleNotFoundError:  # pragma: no cover - optional dependency for better lemmatization
    try:
        import pymorphy2 as _pymorphy
    except ModuleNotFoundError:
        _pymorphy = None

@dataclass(slots=True)
class ValidationResult:
    ok: bool
    reason: str | None = None
    normalized_word: str | None = None
    debug: dict[str, Any] | None = None


class WordValidator:
    def __init__(self, dictionary_packs: dict[str, set[str]] | None = None) -> None:
        self.morph: Any | None = None
        if _pymorphy:
            try:
                self.morph = _pymorphy.MorphAnalyzer()
            except Exception:
                self.morph = None
        self.dictionary_packs = dictionary_packs or {'basic': set(), 'science': set(), 'slang': set()}
        self.non_noun_blocklist = {
            'якобы', 'вроде', 'когда', 'тогда', 'потом', 'всегда', 'никогда', 'ибо', 'чтобы', 'если',
        }

    @staticmethod
    def normalize_word_key(word: str) -> str:
        return word.lower().strip().replace('ё', 'е')

    @staticmethod
    def normalize_letter(letter: str) -> str:
        return letter.lower().strip().replace('ё', 'е')[:1]

    def normalize(self, word: str) -> str:
        prepared = self.normalize_word_key(word)
        if not prepared:
            return prepared
        if not self.morph:
            return prepared
        parsed = self.morph.parse(prepared)
        return parsed[0].normal_form if parsed else prepared

    @staticmethod
    def get_required_letter_from_word(word: str, skip_tail_letters: set[str] | None = None) -> str:
        skip = skip_tail_letters or {'ь', 'ъ', 'ы'}
        clean = word.lower().strip()
        for ch in reversed(clean):
            if ch not in skip:
                return ch
        return clean[-1] if clean else ''

    def validate(
        self,
        word: str,
        current_letter: str,
        used_words: set[str],
        dictionary_pack: str = 'basic',
        extra_words: set[str] | None = None,
    ) -> ValidationResult:
        raw_word = self.normalize_word_key(word)
        used_keys = {self.normalize_word_key(value) for value in used_words}
        if not raw_word:
            return ValidationResult(ok=False, reason='empty_word')
        if len(raw_word.split()) > 1:
            return ValidationResult(ok=False, reason='not_single_word')
        if not re.fullmatch(r'[а-яё]{2,}', word.lower().strip()):
            return ValidationResult(ok=False, reason='invalid_characters')
        expected_letter = self.normalize_letter(current_letter)
        if expected_letter and raw_word and self.normalize_letter(raw_word[0]) != expected_letter:
            return ValidationResult(ok=False, reason='wrong_start_letter')
        if self._is_person_name(raw_word):
            return ValidationResult(ok=False, reason='proper_name_not_allowed')
        if raw_word in self.non_noun_blocklist:
            return ValidationResult(ok=False, reason='noun_only_allowed')
        lemma_key = raw_word
        noun_parses: list[Any] = []
        if self.morph:
            noun_parses = self._noun_parses(raw_word)
            if not noun_parses:
                return ValidationResult(ok=False, reason='noun_only_allowed')

            strict_candidates = [p for p in noun_parses if self._is_initial_nominative_or_indeclinable(raw_word, p)]
            if strict_candidates:
                best = strict_candidates[0]
                lemma_key = self.normalize_word_key(str(best.normal_form))
            else:
                if any(self.normalize_word_key(str(p.normal_form)) == raw_word for p in noun_parses):
                    return ValidationResult(ok=False, reason='nominative_required')
                return ValidationResult(ok=False, reason='use_normal_form_only')

        if lemma_key in used_keys or raw_word in used_keys:
            return ValidationResult(ok=False, reason='already_used')

        pack_words = self.dictionary_packs.get(dictionary_pack, set())
        pack_words = {self.normalize_word_key(w) for w in pack_words}
        extra_words = extra_words or set()
        extra_words = {self.normalize_word_key(w) for w in extra_words}
        in_extra = raw_word in extra_words or lemma_key in extra_words
        in_pack = raw_word in pack_words or lemma_key in pack_words or in_extra

        if pack_words and not in_pack:
            return ValidationResult(ok=False, reason='not_in_dictionary')
        if not pack_words and self.morph and noun_parses and not noun_parses[0].is_known and not in_extra:
            return ValidationResult(ok=False, reason='not_in_dictionary')

        accepted = lemma_key if (lemma_key in pack_words or lemma_key in extra_words) else raw_word
        return ValidationResult(ok=True, normalized_word=accepted)

    def _noun_parses(self, raw_word: str) -> list[Any]:
        if not self.morph:
            return []
        try:
            parses = self.morph.parse(raw_word)
        except Exception:
            return []
        return [p for p in parses if str(p.tag.POS or '') == 'NOUN']

    @staticmethod
    def _is_initial_nominative_or_indeclinable(raw_word: str, parsed: Any) -> bool:
        normal_form = str(parsed.normal_form or '')
        if normal_form != raw_word:
            return False
        case = str(getattr(parsed.tag, 'case', '') or '')
        if case == 'nomn':
            return True
        return case == '' or 'Fixd' in str(parsed.tag)

    def _is_person_name(self, word: str) -> bool:
        if not self.morph:
            return False
        try:
            parses = self.morph.parse(word)
        except Exception:
            return False
        for parsed in parses[:3]:
            tag = str(parsed.tag)
            if 'Geox' in tag:
                continue
            if any(marker in tag for marker in ('Name', 'Surn', 'Patr')):
                return True
        return False

    @staticmethod
    def _looks_like_noise(word: str) -> bool:
        cleaned = word.replace('-', '')
        if len(cleaned) >= 8 and len(set(cleaned)) <= 2:
            return True
        if len(cleaned) >= 9:
            for n in (1, 2, 3):
                if len(cleaned) % n == 0:
                    chunk = cleaned[:n]
                    if chunk * (len(cleaned) // n) == cleaned:
                        return True
        if re.search(r'(.)\1{3,}', cleaned):
            return True
        return False

    @staticmethod
    def _looks_pronounceable(word: str) -> bool:
        cleaned = word.replace('-', '')
        vowels = set('аеёиоуыэюя')
        if not any(ch in vowels for ch in cleaned):
            return False
        cons_run = 0
        vowel_run = 0
        for ch in cleaned:
            if ch in vowels:
                vowel_run += 1
                cons_run = 0
            else:
                cons_run += 1
                vowel_run = 0
            if cons_run > 4 or vowel_run > 3:
                return False
        return True

    @staticmethod
    def _levenshtein(a: str, b: str, max_dist: int = 3) -> int:
        if abs(len(a) - len(b)) > max_dist:
            return max_dist + 1
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            cur = [i]
            row_min = i
            for j, cb in enumerate(b, start=1):
                insert_cost = cur[j - 1] + 1
                delete_cost = prev[j] + 1
                replace_cost = prev[j - 1] + (0 if ca == cb else 1)
                val = min(insert_cost, delete_cost, replace_cost)
                cur.append(val)
                row_min = min(row_min, val)
            if row_min > max_dist:
                return max_dist + 1
            prev = cur
        return prev[-1]

    def _is_typo_like(self, word: str, pack_words: set[str]) -> bool:
        if not pack_words:
            return False
        first = word[0]
        candidates = [w for w in pack_words if w and w[0] == first and abs(len(w) - len(word)) <= 2]
        if not candidates:
            return False
        best = min(self._levenshtein(word, candidate, max_dist=2) for candidate in candidates[:300])
        return best <= 2

    @staticmethod
    def _looks_inflected_form(word: str) -> bool:
        suffixes = (
            'ого', 'его', 'ому', 'ему', 'ыми', 'ими', 'ами', 'ями', 'ах', 'ях',
            'ой', 'ей', 'ом', 'ам', 'ям', 'ую', 'юю', 'ы', 'и', 'е', 'у', 'ю', 'а', 'я',
        )
        if len(word) <= 3:
            return False
        return any(word.endswith(suf) for suf in suffixes)
