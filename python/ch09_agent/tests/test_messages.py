from agent_ch09.core.messages import (
    MessageContractError,
    assistant_message,
    tool_call,
    tool_message,
    user_message,
    validate_tool_pairing,
)


def test_accepts_multi_call_group_in_any_result_order():
    messages = [
        user_message("go"),
        assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))),
        tool_message("B", "b"),
        tool_message("A", "a"),
    ]
    validate_tool_pairing(messages)


def test_rejects_duplicate_ids_and_orphan_results():
    try:
        assistant_message(None, (tool_call("same", "one", "{}"), tool_call("same", "two", "{}")))
        raise AssertionError("expected error")
    except MessageContractError:
        pass
    try:
        validate_tool_pairing([tool_message("orphan", "missing")])
        raise AssertionError("expected error")
    except MessageContractError as error:
        assert "工具结果找不到对应" in str(error)


def test_rejects_incomplete_group():
    try:
        validate_tool_pairing(
            [
                assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))),
                tool_message("A", "a"),
            ]
        )
        raise AssertionError("expected error")
    except MessageContractError as error:
        assert "缺少返回结果" in str(error)
