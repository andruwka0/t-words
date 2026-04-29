import app.services.rarity as rarity_module
from app.services.dictionary_loader import load_basic_words
from app.services.scoring import calculate_score, calculate_score_details
from app.validator import WordValidator


def test_score_rewards_speed_and_rare_letters() -> None:
    slow = calculate_score('арбуз', response_seconds=10)
    fast_rare = calculate_score('ящер', response_seconds=2)
    assert fast_rare > slow


def test_validation_rejects_wrong_letter() -> None:
    validator = WordValidator({'basic': {'арбуз'}})
    result = validator.validate('арбуз', current_letter='б', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'wrong_start_letter'


def test_scoring_supports_extended_rarity_tiers(monkeypatch) -> None:
    monkeypatch.setattr(rarity_module, 'zipf_frequency', lambda _word, _lang: 2.6)
    breakdown = calculate_score_details('экзистенция', response_seconds=2)
    assert breakdown.rarity_tier == 'epic'
    assert breakdown.rarity_bonus == 10


def test_validation_rejects_gibberish_word_without_morph() -> None:
    validator = WordValidator({'basic': {'арбуз'}})
    validator.morph = None
    result = validator.validate('абвгдёё', current_letter='а', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'not_in_dictionary'


def test_validation_does_not_use_wordfreq_as_runtime_allowlist() -> None:
    validator = WordValidator({'basic': {'арбуз'}})
    validator.morph = None
    result = validator.validate('кактус', current_letter='к', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'not_in_dictionary'


def test_validation_uses_dictionary_lemma_not_surface_form() -> None:
    validator = WordValidator({'basic': {'наряд'}})
    result = validator.validate('наряду', current_letter='н', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason in {'use_normal_form_only', 'not_in_dictionary'}


def test_validation_accepts_dictionary_lemma() -> None:
    validator = WordValidator({'basic': {'наряд'}})
    result = validator.validate('наряд', current_letter='н', used_words=set(), dictionary_pack='basic')
    assert result.ok
    assert result.normalized_word == 'наряд'


def test_basic_dictionary_fallback_contains_common_n_words() -> None:
    words = load_basic_words(limit=3000)
    n_words = [w for w in words if w.startswith('н')]
    assert 'кактус' in words
    assert len(n_words) >= 5


def test_validation_rejects_repetitive_noise_without_lexical_libs() -> None:
    validator = WordValidator({'basic': {'арбуз', 'апельсин', 'рак'}})
    validator.morph = None
    result = validator.validate('ауауауауауауа', current_letter='а', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'not_in_dictionary'


def test_validation_rejects_non_nominative_form_when_morph_available() -> None:
    validator = WordValidator({'basic': {'носорог'}})
    if validator.morph is None:
        return
    result = validator.validate('носорога', current_letter='н', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'use_normal_form_only'


def test_validation_blocks_used_lemma_forms() -> None:
    validator = WordValidator({'basic': {'апельсин'}})
    used = {'апельсин'}
    if validator.morph is None:
        result = validator.validate('апельсин', current_letter='а', used_words=used, dictionary_pack='basic')
    else:
        result = validator.validate('апельсина', current_letter='а', used_words=used, dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'already_used'
