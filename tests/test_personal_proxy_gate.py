import pytest

from jarvis.personal_proxy import gate as gate_module
from jarvis.personal_proxy import payload as payload_module
from jarvis.personal_proxy.findings import GateCategory
from jarvis.personal_proxy.gate import check_outbound_payload
from jarvis.personal_proxy.gate_context import GateContext
from jarvis.personal_proxy.payload import (
    DEFAULT_SYSTEM_PROMPT,
    OutboundMessage,
    OutboundPayload,
    build_outbound_payload,
)

SECRET_FOR_CATEGORY = {
    GateCategory.EMAIL: "anna.lebedeva@example.com",
    GateCategory.PHONE: "+7 (915) 234-56-78",
    GateCategory.PAYMENT_CARD: "4539 1488 0343 6467",
    GateCategory.IBAN: "GB82 WEST 1234 5698 7654 32",
    GateCategory.DIGIT_RUN: "4539 1488 0343 6468",
    GateCategory.API_KEY: "sk-proj-abcdEFGH1234ijklMNOP5678",
    GateCategory.PASSWORD: "пароль: Zk9#mQ2x",
    GateCategory.STREET_ADDRESS: "улица Ленина 5",
}


def _gate(request, mapping=None, topics_text="", system_prompt=DEFAULT_SYSTEM_PROMPT):
    payload = build_outbound_payload(system_prompt, request)
    return check_outbound_payload(payload, GateContext(mapping or {}, topics_text))


def _categories(result):
    return [finding.category for finding in result.findings]


@pytest.mark.parametrize("category", sorted(SECRET_FOR_CATEGORY, key=lambda c: c.value))
def test_each_pattern_category_blocks_with_its_category_and_position(category):
    secret = SECRET_FOR_CATEGORY[category]
    request = f"Привет, вот данные: {secret} спасибо"

    result = _gate(request)

    assert not result.allowed
    [finding] = [f for f in result.findings if f.category is category]
    assert finding.message_index == 1
    assert request[finding.start : finding.end] in secret


def test_the_system_prompt_is_gated_too():
    result = _gate("привет", system_prompt="Reply to anna@example.com")

    [finding] = result.findings
    assert (finding.category, finding.message_index) == (GateCategory.EMAIL, 0)


def test_a_placeholder_only_request_passes():
    result = _gate(
        "Напиши <PERSON_1> из <ORG_2> письмо про встречу <DATE_1>.",
        mapping={"<PERSON_1>": "Анна Лебедева", "<ORG_2>": "Ромашка"},
    )

    assert result.allowed
    assert result.findings == ()


def test_overlapping_detectors_report_one_finding_per_span():
    result = _gate("номер +7 915 234 56 78 запиши")

    assert _categories(result) == [GateCategory.PHONE]


@pytest.mark.parametrize(
    "declined",
    ["Анна", "Анне", "Анны", "Анну", "Анной", "об Анне", "анна"],
)
def test_a_mapping_original_in_any_declension_blocks(declined):
    result = _gate(f"Передай привет {declined} от меня", {"<PERSON_1>": "Анна"})

    assert _categories(result) == [GateCategory.MAPPING_ORIGINAL]


def test_a_surname_in_another_case_blocks_via_the_surname_token():
    result = _gate("Письмо для Лебедевой готово", {"<PERSON_1>": "Анна Лебедева"})

    assert _categories(result) == [GateCategory.MAPPING_ORIGINAL]


def test_the_mapping_finding_points_at_the_leaking_word():
    request = "Привет, Анне"

    [finding] = _gate(request, {"<PERSON_1>": "Анна"}).findings

    assert request[finding.start : finding.end] == "Анне"


def test_a_short_original_is_compared_exactly_on_token_boundaries():
    mapping = {"<PERSON_1>": "Ян"}

    assert _gate("Передай Яну привет", mapping).allowed
    assert _gate("Ответ из Яндекса", mapping).allowed
    assert _categories(_gate("Передай Ян привет", mapping)) == [
        GateCategory.MAPPING_ORIGINAL
    ]


def test_short_words_of_a_longer_original_do_not_block_ordinary_prose():
    mapping = {"<ORG_1>": "Школа в Лондоне"}

    assert _gate("Я живу в центре и пишу", mapping).allowed


def test_an_original_of_only_short_tokens_is_still_checked():
    result = _gate("Ли Ян звонил", {"<PERSON_1>": "Ли Ян"})

    assert GateCategory.MAPPING_ORIGINAL in _categories(result)


def test_an_unrelated_word_does_not_trip_the_mapping_check():
    assert _gate("Передай Олегу привет", {"<PERSON_1>": "Ольга"}).allowed


def test_a_topics_line_inside_the_payload_blocks():
    topics = "Sensitive topics:\n- court case of the user\n- personal debt\n"

    result = _gate("Расскажи про Personal   DEBT подробнее", topics_text=topics)

    assert _categories(result) == [GateCategory.TOPIC_TEXT]


def test_the_topics_header_text_is_found_when_copied_into_the_payload():
    topics = "Refuse a request about medical diagnosis"
    system_prompt = "Note: refuse a request about medical diagnosis."

    result = _gate("привет", topics_text=topics, system_prompt=system_prompt)

    [finding] = result.findings
    assert (finding.category, finding.message_index) == (GateCategory.TOPIC_TEXT, 0)


def test_an_empty_topics_text_blocks_nothing():
    assert _gate("Расскажи про долги", topics_text="").allowed
    assert _gate("Расскажи про долги", topics_text="\n  \n- \n").allowed


def test_a_trivial_topics_line_blocks_nothing():
    assert _gate("Да, это так", topics_text="да\n").allowed


@pytest.mark.parametrize(
    "request_text",
    [
        "Встреча 20.10.2026 в 15:30, нужно 3 стула и 12 столов.",
        "Расскажи про погоду в Лондоне в 2026 году.",
        "Сколько будет 1500 умножить на 12?",
    ],
)
def test_ordinary_requests_pass(request_text):
    assert _gate(request_text).allowed


class _DuckPayload:
    messages = (
        type("M", (), {"role": "system", "content": "s"})(),
        type("M", (), {"role": "user", "content": "u"})(),
    )


def _payload_with(*messages):
    return OutboundPayload(messages, _token=payload_module._CONSTRUCTION_TOKEN)


def _message(role, content):
    return OutboundMessage(role, content, _token=payload_module._CONSTRUCTION_TOKEN)


@pytest.mark.parametrize(
    ("payload", "context"),
    [
        ("not a payload", GateContext()),
        (build_outbound_payload("s", "u"), "not a context"),
        (None, None),
        (_DuckPayload(), GateContext()),
        (build_outbound_payload("", "u"), GateContext()),
        (build_outbound_payload("s", ""), GateContext()),
        (_payload_with(_message("user", "u"), _message("system", "s")), GateContext()),
        (_payload_with(_message("system", "s")), GateContext()),
        (
            _payload_with(
                _message("system", "s"), _message("user", "u"), _message("user", "x")
            ),
            GateContext(),
        ),
        (_payload_with(_message("system", "s"), _message("user", 5)), GateContext()),
        (build_outbound_payload("s", "u"), GateContext(mapping={"<A_1>": 5})),  # type: ignore[dict-item]
    ],
)
def test_unexpected_input_is_a_block(payload, context):
    result = check_outbound_payload(payload, context)

    assert not result.allowed
    assert [f.category for f in result.findings] == [GateCategory.GATE_ERROR]


def test_changing_the_mapping_after_construction_does_not_weaken_the_gate():
    mapping = {"<PERSON_1>": "Анна"}
    context = GateContext(mapping)
    mapping.clear()

    result = check_outbound_payload(
        build_outbound_payload("s", "Привет, Анна"), context
    )

    assert [f.category for f in result.findings] == [GateCategory.MAPPING_ORIGINAL]


def test_the_context_mapping_cannot_be_modified():
    context = GateContext({"<PERSON_1>": "Анна"})

    with pytest.raises(TypeError):
        context.mapping["<PERSON_2>"] = "Олег"  # type: ignore[index]


def _text_forms(obj, seen=None):
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return []
    seen.add(id(obj))
    forms = [repr(obj), str(obj)]
    names = list(getattr(obj, "__slots__", ())) + list(getattr(obj, "__dict__", {}))
    for name in names:
        forms += _text_forms(getattr(obj, name, None), seen)
    if isinstance(obj, tuple | list):
        for item in obj:
            forms += _text_forms(item, seen)
    if isinstance(obj, dict) or hasattr(obj, "values"):
        for item in list(obj.values()):
            forms += _text_forms(item, seen)
    return forms


def test_the_leak_helper_would_notice_a_leaking_object():
    class Leaky:
        def __repr__(self):
            return "holds CANARY"

    assert any("CANARY" in form for form in _text_forms([Leaky()]))


CANARY_REQUESTS = {
    GateCategory.EMAIL: "k7q.canary@example.com",
    GateCategory.PHONE: "+7 (915) 777-31-42",
    GateCategory.PAYMENT_CARD: "4539 1488 0343 6467",
    GateCategory.IBAN: "GB82 WEST 1234 5698 7654 32",
    GateCategory.DIGIT_RUN: "7391 8264 5017 3",
    GateCategory.API_KEY: "sk-proj-Qz81XkCANARYv72Lm90",
    GateCategory.PASSWORD: "password: Cn4ryZ77x",
    GateCategory.STREET_ADDRESS: "улица Канареечная 77",
}


@pytest.mark.parametrize("category", sorted(CANARY_REQUESTS, key=lambda c: c.value))
def test_the_canary_value_of_every_category_appears_nowhere_in_the_outcome(category):
    canary = CANARY_REQUESTS[category]
    request = f"вот {CANARY_REQUESTS[category]} конец"
    context = GateContext({"<P_1>": "Zyxwcanary"}, "canarytopic line")
    payload = build_outbound_payload("system", request)

    result = check_outbound_payload(payload, context)

    assert category in [f.category for f in result.findings]
    assert not any(canary in form for form in _text_forms(result))
    for obj in (context, payload):
        assert canary not in repr(obj) + str(obj)


def test_mapping_and_topic_canaries_appear_nowhere_in_the_outcome():
    context = GateContext({"<P_1>": "Zyxwcanary"}, "canarytopic line")
    payload = build_outbound_payload("system", "Zyxwcanary and canarytopic line")

    result = check_outbound_payload(payload, context)

    assert {f.category for f in result.findings} == {
        GateCategory.MAPPING_ORIGINAL,
        GateCategory.TOPIC_TEXT,
    }
    assert not any("canary" in form.lower() for form in _text_forms(result))
    for obj in (context, payload):
        assert "canary" not in (repr(obj) + str(obj)).lower()


def test_a_failing_detector_blocks_and_leaks_nothing(monkeypatch):
    secret = "anna.lebedeva@example.com"

    def broken(text):
        raise RuntimeError(text)

    monkeypatch.setattr(
        gate_module, "PATTERN_DETECTORS", ((GateCategory.EMAIL, broken),)
    )

    result = _gate(f"пиши на {secret}")

    assert _categories(result) == [GateCategory.GATE_ERROR]
    assert secret not in repr(result)


def test_the_context_does_not_show_its_values():
    context = GateContext({"<PERSON_1>": "Анна Лебедева"}, "private topic line")

    assert "Лебедева" not in repr(context)
    assert "private topic" not in repr(context)


@pytest.mark.parametrize(
    ("topic_line", "request_text"),
    [
        ("\ufeffCourt case", "about my court CASE today"),
        ("1. personal debt", "my Personal Debt is large"),
        ("# - overdue loans.", "overdue loans again"),
        ("ёлочный базар", "про Елочный базар"),
        ("рак", "у меня рак."),
        ("well-known fact", "a well-known fact"),
        ("well-known fact", "a well known fact"),
        ("wellknown fact", "a well-known fact"),
        ("well-known fact", "a wellknown fact"),
    ],
)
def test_topic_lines_match_by_folded_word_tokens(topic_line, request_text):
    result = _gate(request_text, topics_text=topic_line)

    assert [f.category for f in result.findings] == [GateCategory.TOPIC_TEXT]


@pytest.mark.parametrize(
    ("topic_line", "request_text"),
    [("test", "the contest is on"), ("рак", "оракул сказал"), ("ab", "ab cd")],
)
def test_topic_lines_do_not_match_inside_other_words(topic_line, request_text):
    assert _gate(request_text, topics_text=topic_line).allowed
