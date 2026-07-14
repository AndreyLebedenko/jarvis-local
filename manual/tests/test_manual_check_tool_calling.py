from manual.manual_check_tool_calling import (
    NATIVE_TOOLS,
    TOOLS,
    TOOLS_BY_NAME,
    ParsedCall,
    Scenario,
    ScenarioOutcome,
    SecondHopOutcome,
    classify_outcome,
    correct_tool_choice,
    fake_tool_result,
    is_false_positive,
    is_missed_call,
    native_tool_schema,
    parse_native_tool_calls,
    parse_prompt_reply,
    prompt_tool_declaration,
    summarize,
    validate_arguments,
)

WEATHER_SPEC = TOOLS_BY_NAME["get_weather"]
SEARCH_SPEC = TOOLS_BY_NAME["search_web"]


# --- native schema / parsing -------------------------------------------------


def test_native_tool_schema_marks_required_and_enum_fields():
    schema = native_tool_schema(WEATHER_SPEC)

    function = schema["function"]
    assert function["name"] == "get_weather"
    params = function["parameters"]
    assert set(params["required"]) == {"city", "units"}
    assert params["properties"]["units"]["enum"] == ["metric", "imperial"]


def test_native_tool_schema_omits_optional_param_from_required():
    schema = native_tool_schema(SEARCH_SPEC)

    params = schema["function"]["parameters"]
    assert params["required"] == ["query"]
    assert "max_results" in params["properties"]


def test_native_tools_cover_every_declared_tool():
    assert len(NATIVE_TOOLS) == len(TOOLS)


def test_parse_native_tool_calls_with_dict_arguments():
    message = {
        "tool_calls": [
            {"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}
        ]
    }

    calls = parse_native_tool_calls(message)

    assert calls == [ParsedCall(name="get_weather", arguments={"city": "Berlin"})]


def test_parse_native_tool_calls_decodes_string_arguments():
    message = {
        "tool_calls": [
            {"function": {"name": "get_weather", "arguments": '{"city": "Berlin"}'}}
        ]
    }

    [call] = parse_native_tool_calls(message)

    assert call.arguments == {"city": "Berlin"}


def test_parse_native_tool_calls_malformed_string_arguments_becomes_empty_dict():
    message = {
        "tool_calls": [{"function": {"name": "get_weather", "arguments": "{oops"}}]
    }

    [call] = parse_native_tool_calls(message)

    assert call.arguments == {}


def test_parse_native_tool_calls_skips_call_without_string_name():
    message = {"tool_calls": [{"function": {"arguments": {}}}]}

    assert parse_native_tool_calls(message) == []


def test_parse_native_tool_calls_with_no_tool_calls_key_is_empty():
    assert parse_native_tool_calls({"content": "hello"}) == []


# --- prompt declaration / reply contract -------------------------------------


def test_prompt_tool_declaration_lists_every_tool_name():
    declaration = prompt_tool_declaration(TOOLS)

    assert "get_weather" in declaration
    assert "search_web" in declaration


def test_parse_prompt_reply_valid_tool_call():
    reply = parse_prompt_reply(
        '{"tool_call": {"name": "get_weather", "arguments": {"city": "Berlin"}}}'
    )

    assert reply.tool_call == ParsedCall(
        name="get_weather", arguments={"city": "Berlin"}
    )
    assert reply.final_answer is None
    assert reply.format_error is None


def test_parse_prompt_reply_valid_final_answer():
    reply = parse_prompt_reply('{"final_answer": "It is sunny."}')

    assert reply.final_answer == "It is sunny."
    assert reply.tool_call is None
    assert reply.format_error is None


def test_parse_prompt_reply_tolerates_markdown_json_fence():
    reply = parse_prompt_reply('```json\n{"final_answer": "ok"}\n```')

    assert reply.final_answer == "ok"
    assert reply.format_error is None


def test_parse_prompt_reply_invalid_json_reports_format_error():
    reply = parse_prompt_reply("not json at all")

    assert reply.format_error is not None
    assert reply.tool_call is None
    assert reply.final_answer is None


def test_parse_prompt_reply_top_level_array_is_format_error():
    reply = parse_prompt_reply("[1, 2, 3]")

    assert reply.format_error == "top-level JSON value is not an object"


def test_parse_prompt_reply_tool_call_missing_name_is_format_error():
    reply = parse_prompt_reply('{"tool_call": {"arguments": {}}}')

    assert reply.format_error == "tool_call missing string 'name'"


def test_parse_prompt_reply_tool_call_arguments_not_object_is_format_error():
    reply = parse_prompt_reply(
        '{"tool_call": {"name": "get_weather", "arguments": "oops"}}'
    )

    assert reply.format_error == "tool_call 'arguments' is not an object"


def test_parse_prompt_reply_final_answer_not_string_is_format_error():
    reply = parse_prompt_reply('{"final_answer": 42}')

    assert reply.format_error == "final_answer is not a string"


def test_parse_prompt_reply_neither_key_is_format_error():
    reply = parse_prompt_reply('{"unrelated": true}')

    assert (
        reply.format_error == "JSON object has neither 'tool_call' nor 'final_answer'"
    )


# --- argument schema validation ----------------------------------------------


def test_validate_arguments_accepts_fully_valid_call():
    errors = validate_arguments(WEATHER_SPEC, {"city": "Berlin", "units": "metric"})

    assert errors == []


def test_validate_arguments_flags_missing_required_argument():
    errors = validate_arguments(WEATHER_SPEC, {"city": "Berlin"})

    assert any("missing required argument 'units'" in error for error in errors)


def test_validate_arguments_flags_wrong_type():
    errors = validate_arguments(SEARCH_SPEC, {"query": "news", "max_results": "five"})

    assert any("wrong type" in error for error in errors)


def test_validate_arguments_flags_invalid_enum_value():
    errors = validate_arguments(WEATHER_SPEC, {"city": "Berlin", "units": "kelvin"})

    assert any("not in" in error for error in errors)


def test_validate_arguments_flags_unexpected_extra_argument():
    errors = validate_arguments(
        WEATHER_SPEC, {"city": "Berlin", "units": "metric", "forecast_days": 3}
    )

    assert any("unexpected argument 'forecast_days'" in error for error in errors)


def test_validate_arguments_boolean_true_is_not_a_valid_integer():
    errors = validate_arguments(SEARCH_SPEC, {"query": "news", "max_results": True})

    assert any("wrong type" in error for error in errors)


def test_fake_tool_result_echoes_requested_city():
    result = fake_tool_result(
        ParsedCall(name="get_weather", arguments={"city": "Tokyo"})
    )

    assert result["city"] == "Tokyo"


def test_fake_tool_result_unknown_tool_still_returns_something():
    result = fake_tool_result(ParsedCall(name="unknown_tool", arguments={}))

    assert result == {"ok": True}


# --- outcome classification ---------------------------------------------------


CALL_SCENARIO = Scenario("s", "prompt text", expected_tool="get_weather")
NO_CALL_SCENARIO = Scenario("s", "prompt text", expected_tool=None)


def test_classify_outcome_correct_call_has_no_validation_errors():
    outcome = classify_outcome(
        CALL_SCENARIO,
        "native",
        1,
        0.5,
        tool_called="get_weather",
        arguments={"city": "Berlin", "units": "metric"},
        final_answer_text=None,
        format_error=None,
    )

    assert outcome.validation_errors == []
    assert correct_tool_choice(outcome)
    assert not is_false_positive(outcome)
    assert not is_missed_call(outcome)


def test_classify_outcome_flags_schema_violation():
    outcome = classify_outcome(
        CALL_SCENARIO,
        "native",
        1,
        0.5,
        tool_called="get_weather",
        arguments={"city": "Berlin"},
        final_answer_text=None,
        format_error=None,
    )

    assert outcome.validation_errors != []


def test_classify_outcome_flags_unknown_tool_name():
    outcome = classify_outcome(
        CALL_SCENARIO,
        "native",
        1,
        0.5,
        tool_called="not_a_real_tool",
        arguments={},
        final_answer_text=None,
        format_error=None,
    )

    assert "unknown tool name 'not_a_real_tool'" in outcome.validation_errors


def test_classify_outcome_false_positive_when_no_call_expected():
    outcome = classify_outcome(
        NO_CALL_SCENARIO,
        "prompt",
        1,
        0.5,
        tool_called="get_weather",
        arguments={"city": "Berlin", "units": "metric"},
        final_answer_text=None,
        format_error=None,
    )

    assert is_false_positive(outcome)
    assert not correct_tool_choice(outcome)


def test_classify_outcome_missed_call_when_expected_but_absent():
    outcome = classify_outcome(
        CALL_SCENARIO,
        "prompt",
        1,
        0.5,
        tool_called=None,
        arguments=None,
        final_answer_text="I don't know.",
        format_error=None,
    )

    assert is_missed_call(outcome)


def test_classify_outcome_no_call_expected_and_none_made_is_correct():
    outcome = classify_outcome(
        NO_CALL_SCENARIO,
        "prompt",
        1,
        0.5,
        tool_called=None,
        arguments=None,
        final_answer_text="A recursive function calls itself.",
        format_error=None,
    )

    assert correct_tool_choice(outcome)
    assert not is_false_positive(outcome)
    assert not is_missed_call(outcome)


# --- summarize ------------------------------------------------------------


def _outcome(
    strategy, expected_tool, tool_called, validation_errors=(), format_error=None
):
    return ScenarioOutcome(
        strategy=strategy,
        scenario_key="k",
        run_index=1,
        wall_seconds=0.1,
        expected_tool=expected_tool,
        tool_called=tool_called,
        arguments={} if tool_called else None,
        validation_errors=list(validation_errors),
        format_error=format_error,
    )


def test_summarize_correct_call_rate():
    outcomes = [
        _outcome("native", "get_weather", "get_weather"),
        _outcome("native", "get_weather", None),
    ]

    summary = summarize(outcomes)["native"]

    assert summary.correct_call_rate == 0.5


def test_summarize_false_positive_rate():
    outcomes = [
        _outcome("native", None, None),
        _outcome("native", None, "get_weather"),
    ]

    summary = summarize(outcomes)["native"]

    assert summary.false_positive_rate == 0.5


def test_summarize_schema_validity_rate_only_counts_calls_that_happened():
    outcomes = [
        _outcome("native", "get_weather", "get_weather", validation_errors=[]),
        _outcome("native", "get_weather", "get_weather", validation_errors=["bad"]),
        _outcome("native", None, None),
    ]

    summary = summarize(outcomes)["native"]

    assert summary.schema_validity_rate == 0.5


def test_summarize_format_error_rate():
    outcomes = [
        _outcome("prompt", "get_weather", "get_weather"),
        _outcome("prompt", "get_weather", None, format_error="invalid JSON"),
    ]

    summary = summarize(outcomes)["prompt"]

    assert summary.format_error_rate == 0.5


def test_summarize_two_step_rate_ignores_scenarios_without_a_first_hop_call():
    clean = _outcome("native", "get_weather", "get_weather")
    clean.second_hop = SecondHopOutcome(
        ran=True, final_answer_present=True, spurious_tool_call=False, format_error=None
    )
    spurious = _outcome("native", "get_weather", "get_weather")
    spurious.second_hop = SecondHopOutcome(
        ran=True, final_answer_present=True, spurious_tool_call=True, format_error=None
    )
    skipped = _outcome("native", "get_weather", None)
    skipped.second_hop = SecondHopOutcome(
        ran=False,
        final_answer_present=False,
        spurious_tool_call=False,
        format_error=None,
    )

    summary = summarize([clean, spurious, skipped])["native"]

    assert summary.two_step_no_spurious_call_rate == 0.5


def test_summarize_two_step_rate_is_none_without_any_second_hop():
    outcomes = [_outcome("native", "get_weather", "get_weather")]

    summary = summarize(outcomes)["native"]

    assert summary.two_step_no_spurious_call_rate is None
