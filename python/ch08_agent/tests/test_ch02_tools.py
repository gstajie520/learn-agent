"""第二章工具集成测试：验证 P01 和 P02 配置的工具注册正确性。

这是什么：测试不同章节 Profile 加载的工具集差异
Java 类比：类似 Ch02ToolsIntegrationTest 测试类
为什么需要：确保 P01 只有 shell，P02 增加了文件工具，避免能力越级
"""

from pathlib import Path

from agent_ch08.adapters.filesystem import LocalWorkspaceFileSystem
from agent_ch08.bootstrap import build_agent
from agent_ch08.core.commands import CommandResult
from agent_ch08.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch08.core.model import ModelReply
from agent_ch08.core.profiles import P01, P02, ChapterProfile
from agent_ch08.features.builtin_tools import create_chapter_two_tools


class FakeModel:
    """测试用的模型 Mock。

    这是什么：预设响应队列的假模型实现
    Java 类比：类似 Mockito.mock(ModelClient.class) 的测试替身
    为什么需要：避免真实 API 调用，让测试快速且可预测
    """

    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class FakeCommandRunner:
    """测试用的命令执行器 Mock。

    这是什么：返回固定成功结果的假命令执行器
    Java 类比：类似 when(runner.run()).thenReturn(successResult) 的 Stub
    为什么需要：避免真实执行 PowerShell 命令，让测试可以在任何环境运行
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        return CommandResult("unused", 0, False, False)


def test_p01_and_p02_tool_sets_are_separate(tmp_path: Path) -> None:
    p01 = build_agent(
        P01,
        FakeModel([ModelReply(assistant_message("ok"), "stop")]),
        str(tmp_path),
        command_runner=FakeCommandRunner(),
    )
    p02_model = FakeModel([ModelReply(assistant_message("ok"), "stop")])
    p02 = build_agent(
        P02,
        p02_model,
        str(tmp_path),
        command_runner=FakeCommandRunner(),
        file_system=LocalWorkspaceFileSystem(),
    )
    p01.run("ok")
    p02.run("ok")
    assert [tool.name for tool in p01._tools.snapshot().openai_tools()] == ["shell"]
    assert [tool.name for tool in p02._tools.snapshot().openai_tools()] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
    ]


def test_composition_rejects_a_forged_profile(tmp_path: Path) -> None:
    forged = ChapterProfile(2, P02.capabilities)
    try:
        build_agent(forged, FakeModel([]), str(tmp_path), command_runner=FakeCommandRunner())
        raise AssertionError("应该拒绝伪造的章节配置")
    except ValueError as error:
        assert "固定的章节配置" in str(error)


def test_model_can_write_edit_read_and_glob_in_one_turn(tmp_path: Path) -> None:
    model = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None,
                    (
                        tool_call(
                            "write",
                            "write_file",
                            '{"path":"note.txt","content":"alpha\\nbeta\\nalpha\\n"}',
                        ),
                        tool_call(
                            "edit",
                            "edit_file",
                            '{"path":"note.txt","old_text":"alpha","new_text":"gamma"}',
                        ),
                        tool_call("read", "read_file", '{"path":"note.txt"}'),
                        tool_call("glob", "glob", '{"pattern":"**/*.txt"}'),
                    ),
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("完成。"), "stop"),
        ]
    )
    runner = build_agent(
        P02,
        model,
        str(tmp_path),
        command_runner=FakeCommandRunner(),
        file_system=LocalWorkspaceFileSystem(),
    )
    result = runner.run("写入并读取 note.txt")
    assert result.final_text == "完成。"
    assert result.history[2].content.startswith("工具执行错误") is False
    assert result.history[3].content.startswith("工具执行错误") is False
    assert "gamma" in result.history[4].content
    assert result.history[5].content == "note.txt"
    validate_tool_pairing(result.history)


def test_extra_fields_are_rejected_before_file_side_effect(tmp_path: Path) -> None:
    registry = create_chapter_two_tools(FakeCommandRunner(), LocalWorkspaceFileSystem())
    result = registry.invoke(
        registry.prepare(tool_call("x", "read_file", '{"path":"x","extra":true}')),
        type("Context", (), {"workspace": str(tmp_path), "identity": "test"})(),
    )
    assert result.is_error is True
    assert result.error_code == "invalid_arguments"
