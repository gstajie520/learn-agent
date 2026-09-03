"""消息领域模型测试。

这是什么：测试工具调用配对契约、消息构造函数、ID 唯一性检查。
Java 类比：类似 MessageDTOTest，验证领域对象的不变式和校验逻辑。
为什么需要：消息配对错误会导致 API 拒绝请求，必须在发送前捕获。
"""

from agent_ch03.core.messages import (
    MessageContractError,
    assistant_message,
    tool_call,
    tool_message,
    user_message,
    validate_tool_pairing,
)


def test_accepts_multi_call_group_in_any_result_order():
    messages = [user_message("go"), assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))), tool_message("B", "b"), tool_message("A", "a")]
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
        validate_tool_pairing([assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))), tool_message("A", "a")])
        raise AssertionError("expected error")
    except MessageContractError as error:
        assert "缺少返回结果" in str(error)
