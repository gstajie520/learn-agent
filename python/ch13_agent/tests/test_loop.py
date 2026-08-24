from dataclasses import dataclass

from agent_ch13.bootstrap import build_agent
from agent_ch13.core.commands import CommandResult
from agent_ch13.core.loop import AgentLimitError
from agent_ch13.core.messages import assistant_message, tool_call
from agent_ch13.core.model import ModelReply
from agent_ch13.core.profiles import P01


@dataclass
class FakeModel:
    """假的模型客户端。

    它不访问 DeepSeek，而是按顺序返回我们提前写好的答案。
    Java 中相当于手写 Stub，`requests` 用来记录 Service 到底调用了什么。
    """

    replies: list[ModelReply]
    requests: list = None

    def __post_init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class FakeCommandRunner:
    """假的命令执行器，不启动真实 PowerShell。"""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, command, cwd, timeout_ms=None):
        self.calls.append((command, cwd, timeout_ms))
        return self.result


def test_loop_executes_tool_then_returns_final_text(tmp_path):
    """本章最重要的测试：完整演示“模型 -> 工具 -> 模型”的两轮闭环。"""
    # 第一次模型回答不提供最终文本，而是要求调用 shell。
    # 第二次模型已经看到了工具结果，所以给出最终中文回答。
    model = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None, (tool_call("call-1", "shell", '{"command":"Write-Output 42"}'),)
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("PowerShell 返回 42。"), "stop"),
        ]
    )
    # Fake 命令执行器固定返回 42，不依赖本机 PowerShell。
    commands = FakeCommandRunner(CommandResult("42", 0, False, False))

    # build_agent 类似 Spring 测试配置：把两个 Fake 注入真正的 AgentRunner。
    runner = build_agent(P01, model, str(tmp_path), command_runner=commands)

    # 从这里正式进入 AgentRunner.run()，阅读源码时可以对 run 按 Ctrl+B。
    result = runner.run("运行命令")

    # 下面不是测试实现细节，而是在描述我们期待的业务行为。
    assert result.final_text == "PowerShell 返回 42。"
    assert commands.calls[0][0] == "Write-Output 42"
    assert result.turns == 2


def test_loop_enforces_max_turns(tmp_path):
    """模型如果一直调用工具，Agent 必须在达到上限后停止。"""
    model = FakeModel(
        [
            ModelReply(
                assistant_message(None, (tool_call("a", "shell", '{"command":"pwd"}'),)),
                "tool_calls",
            ),
            ModelReply(
                assistant_message(None, (tool_call("b", "shell", '{"command":"pwd"}'),)),
                "tool_calls",
            ),
        ]
    )
    runner = build_agent(
        P01,
        model,
        str(tmp_path),
        command_runner=FakeCommandRunner(CommandResult("ok", 0, False, False)),
        max_turns=2,
    )
    try:
        runner.run("一直调用")
        raise AssertionError("expected limit")
    except AgentLimitError:
        pass
