from __future__ import annotations

import pytest

from app.validator import WordValidator


def _validator(pack: set[str] | None = None) -> WordValidator:
    return WordValidator({'basic': pack or set()})


def test_accepts_valid_noun_in_initial_form() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate('арбуз', current_letter='а', used_words=set(), dictionary_pack='basic')
    assert result.ok
    assert result.normalized_word == 'арбуз'


def test_rejects_wrong_start_letter() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate('арбуз', current_letter='б', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'wrong_start_letter'


def test_rejects_phrase_with_spaces() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate('арбуз сок', current_letter='а', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'not_single_word'


def test_rejects_invalid_characters() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate('арбуз2', current_letter='а', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'invalid_characters'


def test_rejects_known_noun_if_not_in_pack() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate('носорог', current_letter='н', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'not_in_dictionary'


def test_allows_extra_words_override() -> None:
    validator = _validator({'арбуз'})
    result = validator.validate(
        'носорог',
        current_letter='н',
        used_words=set(),
        dictionary_pack='basic',
        extra_words={'носорог'},
    )
    assert result.ok


def test_rejects_used_lemma_forms() -> None:
    validator = _validator({'апельсин'})
    if validator.morph is None:
        result = validator.validate('апельсин', current_letter='а', used_words={'апельсин'}, dictionary_pack='basic')
    else:
        result = validator.validate('апельсина', current_letter='а', used_words={'апельсин'}, dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'already_used'


@pytest.mark.skipif(WordValidator({'basic': set()}).morph is None, reason='morph analyzer is unavailable')
def test_rejects_non_initial_noun_form() -> None:
    validator = _validator({'носорог'})
    result = validator.validate('носорога', current_letter='н', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'use_normal_form_only'


@pytest.mark.skipif(WordValidator({'basic': set()}).morph is None, reason='morph analyzer is unavailable')
def test_rejects_person_names() -> None:
    validator = _validator({'иван'})
    result = validator.validate('иван', current_letter='и', used_words=set(), dictionary_pack='basic')
    assert not result.ok
    assert result.reason == 'proper_name_not_allowed'
