"""消息契约验证测试。

这是什么：消息结构和配对规则的单元测试
Java 类比：类似 MessageValidatorTest 测试类
为什么需要：验证工具调用与结果的配对规则，确保消息序列的正确性
"""

from agent_ch02.core.messages import (
    MessageContractError,
    assistant_message,
    tool_call,
    tool_message,
    user_message,
    validate_tool_pairing,
)


def test_accepts_multi_call_group_in_any_result_order():
    """验证多工具调用的结果可以乱序返回。

    这是什么：并行工具调用的配对验证测试
    Java 类比：类似 @Test void testMultiToolCallOrderIndependent()
    为什么需要：确保工具结果可以按任意顺序返回，只要 ID 匹配即可
    """
    messages = [user_message("go"), assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))), tool_message("B", "b"), tool_message("A", "a")]  # 结果乱序
    validate_tool_pairing(messages)  # 应该验证通过


def test_rejects_duplicate_ids_and_orphan_results():
    """验证拒绝重复 ID 和孤立结果。

    这是什么：消息契约错误检测测试
    Java 类比：类似 @Test void testRejectInvalidMessages()
    为什么需要：确保工具调用 ID 唯一，且每个结果都有对应的调用
    """
    try:
        assistant_message(None, (tool_call("same", "one", "{}"), tool_call("same", "two", "{}")))  # 重复 ID
        raise AssertionError("expected error")  # 不应该到达这里
    except MessageContractError:  # 应该抛出契约错误
        pass
    try:
        validate_tool_pairing([tool_message("orphan", "missing")])  # 孤立的工具结果
        raise AssertionError("expected error")  # 不应该到达这里
    except MessageContractError as error:  # 应该抛出契约错误
        assert "工具结果找不到对应" in str(error)  # 验证错误消息


def test_rejects_incomplete_group():
    """验证拒绝不完整的工具调用组。

    这是什么：工具调用完整性验证测试
    Java 类比：类似 @Test void testRejectIncompleteToolGroup()
    为什么需要：确保每个工具调用都有对应的结果，防止消息序列不一致
    """
    try:
        validate_tool_pairing([assistant_message(None, (tool_call("a", "one", "{}"), tool_call("b", "two", "{}"))), tool_message("A", "a")])  # 缺少 b 的结果
        raise AssertionError("expected error")  # 不应该到达这里
    except MessageContractError as error:  # 应该抛出契约错误
        assert "缺少返回结果" in str(error)  # 验证错误消息
