from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

try:
    from wordfreq import top_n_list
except ModuleNotFoundError:  # pragma: no cover
    top_n_list = None

try:
    import pymorphy3 as _pymorphy
except ModuleNotFoundError:  # pragma: no cover
    try:
        import pymorphy2 as _pymorphy
    except ModuleNotFoundError:
        _pymorphy = None

RUSSIAN_WORD = re.compile(r'^[а-яё-]{3,24}$')


def _to_noun_lemma(word: str, morph: Any | None) -> str | None:
    if not RUSSIAN_WORD.fullmatch(word):
        return None
    if morph is None:
        return None
    parsed = morph.parse(word)
    if not parsed:
        return None
    best = parsed[0]
    if not best.is_known or str(best.tag.POS or '') != 'NOUN':
        return None
    tag = str(best.tag)
    if any(marker in tag for marker in ('Name', 'Surn', 'Patr', 'Geox')):
        return None
    lemma = best.normal_form.lower().strip().replace('ё', 'е')
    if not RUSSIAN_WORD.fullmatch(lemma):
        return None
    return lemma


@lru_cache(maxsize=1)
def load_basic_words(limit: int = 3000) -> set[str]:
    """Load noun lemmas for game validation (frequency list is not a validation authority)."""
    morph = None
    if _pymorphy:
        try:
            morph = _pymorphy.MorphAnalyzer()
        except Exception:
            morph = None

    words: set[str] = set()
    if top_n_list and morph is not None:
        candidates = top_n_list('ru', 20000)
        for token in candidates:
            word = token.lower().strip().replace('ё', 'е')
            lemma = _to_noun_lemma(word, morph)
            if lemma:
                words.add(lemma)
            if len(words) >= limit:
                break

    if len(words) < limit and morph is not None:
        try:
            iterator = morph.dictionary.words.iter_known_words(prefix='')  # type: ignore[attr-defined]
            for item in iterator:
                token = item[0] if isinstance(item, tuple) else str(item)
                word = token.lower().strip().replace('ё', 'е')
                lemma = _to_noun_lemma(word, morph)
                if lemma:
                    words.add(lemma)
                if len(words) >= limit:
                    break
        except Exception:
            pass

    words.update(
        {
            'апельсин', 'ананас', 'автобус', 'арбуз', 'астра', 'атом',
            'банан', 'берег', 'билет', 'бабочка', 'брусника', 'база',
            'вагон', 'ветер', 'вода', 'ворона', 'вишня', 'вулкан',
            'город', 'гитара', 'гора', 'галерея', 'гвоздика', 'гранат',
            'дом', 'дорога', 'дерево', 'доска', 'диван', 'дракон',
            'ежевика', 'ель', 'ерш', 'енот', 'еж', 'елка',
            'журнал', 'жираф', 'жемчуг', 'жара', 'жест', 'жизнь',
            'замок', 'завод', 'зебра', 'зонт', 'звезда', 'золото',
            'игла', 'ирис', 'инженер', 'история', 'икра', 'идея',
            'кактус', 'книга', 'кошка', 'карта', 'компас', 'камень', 'курица', 'капуста',
            'лимон', 'лиса', 'лодка', 'лампа', 'лес', 'лопата',
            'машина', 'малина', 'метро', 'мост', 'молоко', 'медаль',
            'нота', 'носорог', 'ножницы', 'нитка', 'ночь', 'нора', 'небо', 'налог',
            'облако', 'огонь', 'озеро', 'окно', 'орел', 'олень',
            'поезд', 'пальма', 'папка', 'пила', 'победа', 'пирог',
            'работа', 'ракета', 'река', 'ромашка', 'рынок', 'рука',
            'собака', 'стол', 'сахар', 'самолет', 'север', 'слива',
            'трава', 'телефон', 'тигр', 'тетрадь', 'торт', 'трамвай',
            'улица', 'утка', 'уголь', 'узор', 'урок', 'улыбка',
            'флаг', 'фрукт', 'фонарь', 'футбол', 'фиалка', 'фильм',
            'хлеб', 'холод', 'хоккей', 'хомяк', 'хвоя', 'храм',
            'цветок', 'цирк', 'цепочка', 'центр', 'цифра', 'цитрус',
            'чашка', 'чайник', 'человек', 'часы', 'черника', 'чемодан',
            'школа', 'шар', 'шапка', 'шоссе', 'шум', 'шутка',
            'щавель', 'щенок', 'щетка', 'щит', 'щепка', 'щука',
            'экран', 'экзамен', 'эмблема', 'этаж', 'эра', 'экология',
            'юбка', 'юрист', 'юмор', 'юноша', 'юнга',
            'яблоко', 'якорь', 'ящик', 'ягода', 'ярмарка', 'ястреб',
        }
    )
    return words
