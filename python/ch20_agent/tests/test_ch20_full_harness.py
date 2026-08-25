"""第二十章完整 Harness 的跨能力离线验收。

这个文件是整本教程的"接缝测试"：它不再单独验证某一个状态机，而是从
唯一组合根 `build_agent(P20, ...)` 进入，证明前十九章的能力在同一个
AgentRunner 上同时成立。

Java 对照：类似 Spring Boot 的 `@SpringBootTest` 集成测试——不 mock 内部
协作者，只把最外层边界（模型、命令执行器、MCP 连接）换成可控 fake。

本章关心的三条不变量：
1. 一次模型回复只使用一个 ToolRegistry 快照，动态工具下一轮才可见；
2. 一个 tool call 必须恰好配一个同 ID 的 tool result；
3. Prompt 只做提示，硬边界由 PermissionPolicy 决定。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_ch20.adapters.background_json import JsonBackgroundJobStore
from agent_ch20.adapters.cron_json import JsonCronStore
from agent_ch20.adapters.git import SubprocessGitRunner
from agent_ch20.adapters.mailbox_json import FileMailboxStore
from agent_ch20.adapters.protocol_json import JsonProtocolStore
from agent_ch20.adapters.task_sqlite import SqliteTaskStore
from agent_ch20.bootstrap import build_agent
from agent_ch20.core.events import EventInbox
from agent_ch20.core.hooks import HookRegistry, HookResult
from agent_ch20.core.messages import (
    assistant_message,
    tool_call,
    validate_tool_pairing,
)
from agent_ch20.core.model import ModelReply, ModelRequest
from agent_ch20.core.permissions import PermissionDecision
from agent_ch20.core.profiles import P20
from agent_ch20.features.background import JobSupervisor
from agent_ch20.features.cron import CronRuntime
from agent_ch20.features.mcp_tools import (
    McpCallResult,
    McpPublishedTool,
    McpRuntime,
    McpServerSpec,
    McpToolPolicy,
)
from agent_ch20.features.protocol import ProtocolRuntime
from agent_ch20.features.recovery import RecoveryConfig
from agent_ch20.features.teammates import TeammateRuntime
from agent_ch20.features.work_stealing import WorkStealingRuntime
from agent_ch20.features.worktrees import WorktreeRuntime

# P20 Lead 的固定内置工具面。断言完整列表而不是"包含某几个"，
# 这样任何一章不小心把工具泄漏进 Lead 都会立刻被发现。
LEAD_TOOLS = (
    # 内置工具面（第 1-2 章）。
    "shell",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    # TODO 快照、Subagent 与 Skill 渐进披露（第 5-7 章）。
    "todo_write",
    "task",
    "load_skill",
    # 带租约的 SQLite 任务图与认领（第 12/17 章）。
    "create_task",
    "get_task",
    "list_tasks",
    "claim_task",
    "complete_task",
    # 受控 Git 工作树隔离（第 18 章）。
    "create_worktree",
    "keep_worktree",
    "remove_worktree",
    # MCP 管理工具只安装到 Lead（第 19 章）；远程工具连接成功后才动态发布。
    "connect_mcp",
    "disconnect_mcp",
    # 定时调度、队友生命周期与协作协议（第 14-16 章）。
    "schedule_cron",
    "spawn_teammate",
    "send_message",
    "request_shutdown",
    "review_plan",
)


class AllowApproval:
    """测试审批器：一律放行，把断言焦点留给硬权限边界。

    注意：放行审批不等于放行越界写入。工作区边界由 PermissionPolicy 的
    write_boundary 判断，审批器无权放宽它——这正是第 4.3 节的不变量。
    """

    def decide(self, _request: object) -> PermissionDecision:
        return PermissionDecision("allow", "测试允许", "test")


class NoopAudit:
    """测试审计器：只满足组合根的必填依赖。"""

    def record(self, _request: object, _decision: object) -> None:
        return None


class FakeMcpConnection:
    """不启动子进程的 MCP 连接 fake。

    字段说明：
        close_calls: 记录关闭次数，用于验证资源只被回收一次。
        call_calls: 记录远程调用次数，用于验证未连接时不会误调。
    """

    def __init__(self) -> None:
        self.close_calls = 0
        self.call_calls = 0

    def list_tools(self) -> tuple[McpPublishedTool, ...]:
        """返回与本地 allowlist 精确一致的远程声明。"""
        return (
            McpPublishedTool(
                "lookup",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "查询演示数据",
            ),
        )

    def call_tool(
        self, name: str, arguments: dict[str, object], timeout_seconds: float
    ) -> McpCallResult:
        """返回确定性远程结果，不产生真实副作用。"""
        self.call_calls += 1
        return McpCallResult(
            ({"type": "text", "text": json.dumps(arguments, ensure_ascii=False)},),
            {"name": name},
            False,
        )

    def wait_for_failure(self) -> None:
        """fake 连接不会自行失效。"""

    def close(self) -> None:
        """记录关闭次数，验证 Runner 只回收一次。"""
        self.close_calls += 1


class FakeMcpFactory:
    """总是交付同一个 fake 连接，便于断言 open/close 次数。"""

    def __init__(self, connection: FakeMcpConnection) -> None:
        self.connection = connection
        self.open_calls = 0

    def open(self, _spec: McpServerSpec) -> FakeMcpConnection:
        self.open_calls += 1
        return self.connection


def _system_text(request: ModelRequest) -> str:
    """取出请求中的 system 指令文本，用于区分不同类型的 side-query。"""
    for message in request.messages:
        if message.role == "system":
            return message.content
    return ""


def _side_query_reply(request: ModelRequest) -> ModelReply:
    """统一回答记忆和压缩这两类"无工具 side-query"。

    第九章把记忆做成生命周期组件：模型只能在没有工具的独立请求里建议"选哪条记忆"，
    不能直接读写 `.memory` 文件。这里按 system 指令区分：
    - 选择器请求返回本章种子记忆的名称，使它进入 Prompt 的 `## memory` 段；
    - 其余（提取、整理）返回 `[]`，避免测试期间写入新记忆。
    """
    instruction = _system_text(request)
    if "选择与查询" in instruction:
        return ModelReply(assistant_message('["full-harness"]'), "stop")
    return ModelReply(assistant_message("[]"), "stop")


class HarnessModel:
    """在一次回复里同时连接 MCP 并尝试越界写入的模型 fake。

    这一个回复同时压测三条不变量：动态工具的可见时机、成对的 tool result、
    以及 Prompt 之外的硬权限边界。
    """

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self._started = False

    def complete(self, request: ModelRequest) -> ModelReply:
        # 每次进入模型都校验配对，任何不成对的历史都会在这里立即暴露。
        validate_tool_pairing(request.messages)
        self.requests.append(request)
        # 无工具请求是 memory/compaction 的 side-query，不参与主循环的工具轮。
        if not request.tools:
            return _side_query_reply(request)
        if not self._started:
            self._started = True
            return ModelReply(
                assistant_message(
                    None,
                    (
                        tool_call("connect-p20", "connect_mcp", '{"alias":"fake"}'),
                        tool_call(
                            "escape-p20",
                            "write_file",
                            json.dumps({"path": "../outside.txt", "content": "绝不能写入"}),
                        ),
                    ),
                ),
                "tool_calls",
            )
        return ModelReply(assistant_message("P20 完整 Harness 验证通过"), "stop")


def _git(root: Path, *args: str) -> None:
    """执行 Git 命令；失败直接抛出，避免测试在半初始化仓库上继续。"""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _create_repository(root: Path) -> None:
    """创建一个最小可用的 Git 仓库根目录。

    第 18 章起 Worktree 要求 cwd 是仓库根，因此完整 Harness 的测试必须
    先建立真实仓库，而不是普通临时目录。
    """
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Agent Tutorial")
    _git(root, "config", "user.email", "agent@example.test")
    (root / ".gitignore").write_text(".agent_tutorial/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "initial")


def _write_context_sources(root: Path) -> None:
    """准备动态 Prompt 的两个真实数据源：一个 Skill 和一条项目记忆。"""
    skill = root / "skills" / "harness-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: harness-skill\ndescription: 完整 Harness Skill\n---\n# 私有正文\n",
        encoding="utf-8",
    )
    from agent_ch20.features.memory import MemoryRecord, MemoryStore

    MemoryStore(str(root), id_generator=lambda: "seed").add(
        MemoryRecord(
            "full-harness",
            "完整组合规则",
            "project",
            "P20 必须复用单一 AgentRunner。",
        )
    )


class _Harness:
    """把完整 Harness 的全部运行时聚合成一个测试夹具。

    Java 对照：类似测试里的 `@TestConfiguration`——集中表达"哪些对象必须共享"，
    因为组合根会对这些共享关系做对象身份校验。
    """

    def __init__(self, root: Path, model: object, hooks: HookRegistry) -> None:
        self.root = root
        self.connection = FakeMcpConnection()
        self.factory = FakeMcpFactory(self.connection)
        # 单一 EventInbox：Cron 与后台完成事件必须进入同一个 typed 收件箱。
        inbox = EventInbox()
        self.supervisor = JobSupervisor(JsonBackgroundJobStore(str(root)), inbox)
        self.cron = CronRuntime(JsonCronStore(str(root)), inbox, supervisor=self.supervisor)
        self.mailbox = FileMailboxStore(str(root))
        self.teammates = TeammateRuntime(self.mailbox, inbox, self.supervisor, self.cron)
        self.protocol = ProtocolRuntime(JsonProtocolStore(str(root)), self.teammates)
        # 单一 SqliteTaskStore：Worktree 与 WorkStealing 必须指向同一任务集。
        self.task_store = SqliteTaskStore(str(root))
        self.worktrees = WorktreeRuntime(str(root), self.task_store, SubprocessGitRunner())
        self.worktrees.validate_repository()
        self.work_stealing = WorkStealingRuntime(
            self.task_store, claim_service=self.worktrees
        )
        self.mcp = McpRuntime(
            (
                McpServerSpec(
                    "fake",
                    "unused",
                    (),
                    (McpToolPolicy("lookup", "read"),),
                ),
            ),
            self.factory,
        )
        self.runner = build_agent(
            P20,
            model,  # type: ignore[arg-type]
            str(root),
            approval_provider=AllowApproval(),
            audit_sink=NoopAudit(),
            hooks=hooks,
            recovery_config=RecoveryConfig("primary", "fallback"),
            task_store=self.task_store,
            background_supervisor=self.supervisor,
            cron_runtime=self.cron,
            mailbox_store=self.mailbox,
            teammate_runtime=self.teammates,
            protocol_runtime=self.protocol,
            work_stealing_runtime=self.work_stealing,
            worktree_runtime=self.worktrees,
            mcp_runtime=self.mcp,
        )


def _system_prompt(request: ModelRequest) -> str:
    """取出该次请求的 system prompt；缺失即为组合根缺陷。"""
    for message in request.messages:
        if message.role == "system":
            return message.content
    raise AssertionError("模型请求缺少 system prompt")


def test_full_harness_combines_dynamic_context_mcp_policy_and_pairing(tmp_path: Path) -> None:
    """完整 Harness 的核心整合断言。

    一次回复同时做两件事：连接 MCP（成功）和写工作区外文件（必须被拒）。
    据此验证动态上下文、MCP 边界、消息配对与资源关闭同时成立。
    """
    _create_repository(tmp_path)
    _write_context_sources(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    if outside.exists():
        outside.unlink()

    hook_events: list[str] = []
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda _context: _record(hook_events))
    model = HarnessModel()
    harness = _Harness(tmp_path, model, hooks)

    try:
        result = harness.runner.run("验证完整 Harness")
        # 只保留带工具的主请求，过滤掉 memory/compaction 的 side-query。
        main_requests = [request for request in model.requests if request.tools]
        initial_prompt = _system_prompt(main_requests[0])
        next_prompt = _system_prompt(main_requests[1])
        initial_tools = tuple(tool.name for tool in main_requests[0].tools)
        next_tools = tuple(tool.name for tool in main_requests[1].tools)
        tool_messages = [message for message in result.history if message.role == "tool"]

        assert result.final_text == "P20 完整 Harness 验证通过"
        assert harness.mcp.connected_aliases == ("fake",)
        assert len(main_requests) == 2

        # 不变量 1：动态工具下一轮才可见，本轮快照被密封。
        assert initial_tools == LEAD_TOOLS
        assert "mcp__fake__lookup" not in initial_tools
        assert "mcp__fake__lookup" in next_tools

        # 动态上下文：Skill 目录项和选中记忆进入 Prompt，Skill 正文不进入。
        assert "harness-skill" in initial_prompt
        assert "完整 Harness Skill" in initial_prompt
        assert "P20 必须复用单一 AgentRunner。" in initial_prompt
        assert "私有正文" not in initial_prompt

        # runtime_status 固定在 Prompt 末尾，并随 MCP 连接状态变化。
        assert initial_prompt.endswith(
            '## runtime_status\n{"mcp_connections":[],"pending_work":false}'
        )
        assert next_prompt.endswith(
            '## runtime_status\n{"mcp_connections":["fake"],"pending_work":false}'
        )
        assert "mcp__fake__lookup" not in initial_prompt
        assert "mcp__fake__lookup" in next_prompt

        # 不变量 3：Prompt 不是授权边界，越界写入必须被硬拒绝。
        assert not outside.exists()
        assert tool_messages[1].content.startswith("工具执行错误 [permission_denied]")

        # 不变量 2：两个 tool call 各得一个同 ID 结果，一个失败不影响另一个。
        assert [message.tool_call_id for message in tool_messages] == [
            "connect-p20",
            "escape-p20",
        ]
        validate_tool_pairing(result.history)

        assert hook_events == ["UserPromptSubmit"]
        # 未被模型调用过的远程工具不能产生任何远程请求。
        assert harness.connection.call_calls == 0
    finally:
        harness.runner.close()
        # 关闭是业务行为：MCP 连接必须被回收，且只回收一次。
        assert harness.mcp.is_closed
        assert harness.connection.close_calls == 1
        assert not harness.cron.has_pending_work
        assert not harness.teammates.has_pending_work


def _record(sink: list[str]) -> HookResult:
    """记录 Hook 触发但不改变业务结果。"""
    sink.append("UserPromptSubmit")
    return HookResult()


def test_runtime_status_reports_pending_background_work(tmp_path: Path) -> None:
    """runtime_status 的 pending_work 必须反映真实后台状态，而不是常量。"""
    _create_repository(tmp_path)
    model = HarnessModel()
    harness = _Harness(tmp_path, model, HookRegistry())
    try:
        # 直接读取组合根注入的状态函数所依赖的同步 getter。
        assert not harness.supervisor.has_pending_work
        assert not harness.cron.has_pending_work
        assert not harness.teammates.has_pending_work
        result = harness.runner.run("验证状态段落")
        prompt = _system_prompt(next(r for r in model.requests if r.tools))
        # 没有异步工作时 pending_work 必须是 false，而不是缺失该字段。
        assert '"pending_work":false' in prompt
        assert result.final_text == "P20 完整 Harness 验证通过"
    finally:
        harness.runner.close()


def test_close_is_idempotent_and_releases_every_runtime(tmp_path: Path) -> None:
    """重复关闭必须安全：资源只回收一次，第二次调用不抛异常。"""
    _create_repository(tmp_path)
    harness = _Harness(tmp_path, HarnessModel(), HookRegistry())
    harness.runner.run("验证关闭边界")
    harness.runner.close()
    first_close_calls = harness.connection.close_calls
    # 再次关闭不能重复回收，也不能抛异常。
    harness.runner.close()
    assert harness.connection.close_calls == first_close_calls
    assert harness.mcp.is_closed
