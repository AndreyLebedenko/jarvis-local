import random

import pytest

from jarvis.audio.speech_markup import parse_speech_markup
from jarvis.personal_proxy.common.speech_tags import strip_speech_control_tags


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<speak>Hello</speak>", "Hello"),
        ('Hi <lang xml:lang="en">there</lang> you', "Hi there you"),
        ("<SPEAK>Loud</SPEAK>", "Loud"),
        ("<lang lang='ru'>x</lang>", "x"),
        ("</lang></speak>text", "text"),
    ],
)
def test_control_tags_are_removed(text, expected):
    assert strip_speech_control_tags(text) == expected


def test_a_tag_rebuilt_by_the_removal_is_removed_too():
    assert strip_speech_control_tags("<<lang>speak>kept") == "kept"


@pytest.mark.parametrize(
    "text",
    [
        "List<String> is a type",
        "a < b and c > d",
        "<div>block</div>",
        "<language>not a control tag</language>",
        "plain **markdown** and - lists",
        "",
    ],
)
def test_everything_else_is_unchanged(text):
    assert strip_speech_control_tags(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('Hello <lang xml:lang="en"', "Hello "),
        ("Hello <speak", "Hello "),
        ("Hello </lang", "Hello "),
        ("Hello <SPEAK foo=1", "Hello "),
        ('Hello <lang xml:lang="en" more', "Hello "),
        ('xml:lang="en">rest', "rest"),
        ("ng lang='en' >rest", "rest"),
        ("x <lang xml:lang='en'/>y", "x y"),
    ],
)
def test_unterminated_tails_and_leading_attribute_fragments_are_removed(text, expected):
    assert strip_speech_control_tags(text) == expected


def test_a_fragment_that_is_not_a_control_tag_stays():
    text = "<language and <langs> and a <b"

    assert strip_speech_control_tags(text) == text


_SENTENCES = [
    'Hello <lang xml:lang="en">world</lang> and <speak>more</speak> text.',
    "Say <lang lang='en'>hi</lang> then <SPEAK>x</SPEAK>.",
    'A </lang> b <lang xml:lang = "en" >c</lang> d.',
]


def _languages(text):
    return {segment.language for segment in parse_speech_markup(text)}


def test_two_stripped_halves_never_recombine_into_a_steering_tag():
    rng = random.Random(20261022)
    for sentence in _SENTENCES:
        for cut in range(len(sentence) + 1):
            first = strip_speech_control_tags(sentence[:cut])
            second = strip_speech_control_tags(sentence[cut:])
            for joined in (first + second, first + " " + second):
                assert _languages(joined) <= {"ru"}, (sentence, cut)
    for _ in range(300):
        sentence = rng.choice(_SENTENCES)
        cut = rng.randrange(len(sentence) + 1)
        halves = [
            strip_speech_control_tags(sentence[:cut]),
            strip_speech_control_tags(sentence[cut:]),
        ]
        for separator in ("", " "):
            assert _languages(separator.join(halves)) <= {"ru"}, (sentence, cut)
