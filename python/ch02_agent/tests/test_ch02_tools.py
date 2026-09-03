"""第二章工具集成测试。

这是什么：测试第二章工具注册和执行的集成测试
Java 类比：类似 @SpringBootTest 集成测试类
为什么需要：验证工具正确注册、章节配置隔离和多工具协作场景
"""

from pathlib import Path

from agent_ch02.adapters.filesystem import LocalWorkspaceFileSystem
from agent_ch02.bootstrap import build_agent
from agent_ch02.core.commands import CommandResult
from agent_ch02.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch02.core.model import ModelReply
from agent_ch02.core.profiles import P01, P02, ChapterProfile
from agent_ch02.features.builtin_tools import create_chapter_two_tools


class FakeModel:
    """测试用的假模型客户端。

    这是什么：模型客户端的测试替身
    Java 类比：类似 @MockBean class FakeModelClient implements ModelClient
    为什么需要：隔离外部 API 依赖，提供可预测的模型响应
    """
    def __init__(self, replies: list[ModelReply]) -> None:
        """初始化假模型，预设响应列表。

        这是什么：构造器，接收预设的响应队列
        Java 类比：类似测试桩的构造器初始化
        为什么需要：提供确定性的模型行为，便于断言验证
        """
        self.replies = replies  # 预设的响应队列
        self.requests = []  # 记录所有请求用于验证

    def complete(self, request):
        """返回预设的下一个响应。

        这是什么：模型调用方法的测试实现
        Java 类比：类似 @Override ModelReply complete(ModelRequest request)
        为什么需要：记录请求并返回预设响应，支持测试验证
        """
        self.requests.append(request)  # 记录请求
        return self.replies.pop(0)  # 返回队列中的下一个响应


class FakeCommandRunner:
    """测试用的假命令执行器。

    这是什么：命令执行器的测试替身
    Java 类比：类似 @MockBean class FakeCommandRunner implements CommandRunner
    为什么需要：避免测试时真实执行系统命令，提供可控的结果
    """
    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """返回固定的成功结果。

        这是什么：命令执行方法的测试实现
        Java 类比：类似 @Override CommandResult run(String cmd, String cwd)
        为什么需要：提供无副作用的命令执行模拟
        """
        return CommandResult("unused", 0, False, False)  # 返回固定的成功结果


def test_p01_and_p02_tool_sets_are_separate(tmp_path: Path) -> None:
    """验证第一章和第二章的工具集是独立的。

    这是什么：章节工具隔离的测试用例
    Java 类比：类似 @Test void testToolSetIsolation()
    为什么需要：确保章节配置正确隔离工具集，防止交叉污染
    """
    p01 = build_agent(P01, FakeModel([ModelReply(assistant_message("ok"), "stop")]), str(tmp_path), command_runner=FakeCommandRunner())  # 构建第一章 Agent
    p02_model = FakeModel([ModelReply(assistant_message("ok"), "stop")])
    p02 = build_agent(P02, p02_model, str(tmp_path), command_runner=FakeCommandRunner(), file_system=LocalWorkspaceFileSystem())  # 构建第二章 Agent
    p01.run("ok")  # 执行第一章 Agent
    p02.run("ok")  # 执行第二章 Agent
    assert [tool.name for tool in p01._tools.snapshot().openai_tools()] == ["shell"]  # 第一章只有 shell
    assert [tool.name for tool in p02._tools.snapshot().openai_tools()] == ["shell", "read_file", "write_file", "edit_file", "glob"]  # 第二章有五个工具


def test_composition_rejects_a_forged_profile(tmp_path: Path) -> None:
    """验证组合根拒绝伪造的章节配置。

    这是什么：配置安全性测试用例
    Java 类比：类似 @Test void testRejectForgedProfile()
    为什么需要：确保只接受预定义的章节配置常量，防止配置伪造
    """
    forged = ChapterProfile(2, P02.capabilities)  # 创建伪造的配置对象
    try:
        build_agent(forged, FakeModel([]), str(tmp_path), command_runner=FakeCommandRunner())  # 尝试使用伪造配置
        raise AssertionError("应该拒绝伪造的章节配置")  # 不应该到达这里
    except ValueError as error:  # 应该抛出 ValueError
        assert "固定的章节配置" in str(error)  # 验证错误消息


def test_model_can_write_edit_read_and_glob_in_one_turn(tmp_path: Path) -> None:
    """验证模型可以在一轮中执行写入、编辑、读取和搜索操作。

    这是什么：多工具协作测试用例
    Java 类比：类似 @Test void testMultiToolExecution()
    为什么需要：验证工具可以在单轮中正确执行多个操作，确保状态一致性
    """
    model = FakeModel([
        ModelReply(assistant_message(None, (
            tool_call("write", "write_file", '{"path":"note.txt","content":"alpha\\nbeta\\nalpha\\n"}'),  # 写入文件
            tool_call("edit", "edit_file", '{"path":"note.txt","old_text":"alpha","new_text":"gamma"}'),  # 编辑文件
            tool_call("read", "read_file", '{"path":"note.txt"}'),  # 读取文件
            tool_call("glob", "glob", '{"pattern":"**/*.txt"}'),  # 搜索文件
        )), "tool_calls"),
        ModelReply(assistant_message("完成。"), "stop"),  # 最终响应
    ])
    runner = build_agent(P02, model, str(tmp_path), command_runner=FakeCommandRunner(), file_system=LocalWorkspaceFileSystem())  # 构建第二章 Agent
    result = runner.run("写入并读取 note.txt")  # 执行任务
    assert result.final_text == "完成。"  # 验证最终输出
    assert result.history[2].content.startswith("工具执行错误") is False  # 写入成功
    assert result.history[3].content.startswith("工具执行错误") is False  # 编辑成功
    assert "gamma" in result.history[4].content  # 读取到编辑后的内容
    assert result.history[5].content == "note.txt"  # glob 找到文件
    validate_tool_pairing(result.history)  # 验证消息配对正确


def test_extra_fields_are_rejected_before_file_side_effect(tmp_path: Path) -> None:
    """验证多余字段在文件操作前被拒绝。

    这是什么：参数验证安全性测试用例
    Java 类比：类似 @Test void testStrictArgumentValidation()
    为什么需要：确保严格验证参数，防止注入攻击和意外副作用
    """
    registry = create_chapter_two_tools(FakeCommandRunner(), LocalWorkspaceFileSystem())  # 创建工具注册表
    result = registry.invoke(registry.prepare(tool_call("x", "read_file", '{"path":"x","extra":true}')), type("Context", (), {"workspace": str(tmp_path), "identity": "test"})())  # 调用带多余字段的工具
    assert result.is_error is True  # 应该返回错误
    assert result.error_code == "invalid_arguments"  # 错误码应为参数无效
