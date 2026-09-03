"""后台任务领域模型、Supervisor 和工具分流器。

这是什么：第 13 章的核心特性，实现长时间工具的异步执行
Java 类比：类似 ExecutorService + CompletableFuture + EventBus 的组合
为什么需要：避免编译、部署等长时间操作阻塞 Agent 循环，超时保护用户体验
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ..core.events import EventInbox, RuntimeEvent
from ..core.tools import (
    PreparedToolCall,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)

# 后台任务系统的常量定义

# 这是什么：标准 UUID v4 格式的正则表达式
# Java 类比：UUID.fromString() 会校验格式
# 为什么需要：防止任意字符串作为 job_id 参与文件路径拼接，避免路径穿越攻击
CANONICAL_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# 这是什么：后台任务的 6 种状态枚举
# Java 类比：enum Status { RUNNING, COMPLETED, FAILED, TIMED_OUT, CANCELLED, INTERRUPTED }
# 为什么需要：明确状态迁移规则，running 是唯一非终态，其他都是终态
STATUSES = ("running", "completed", "failed", "timed_out", "cancelled", "interrupted")

# 这是什么：启发式识别后台任务的关键词列表
# Java 类比：List.of("cargo build", "compile", ...) 用于 contains 判断
# 为什么需要：当 run_in_background 为 None 时，通过命令内容自动判断是否需要后台执行
BACKGROUND_MARKERS = ("cargo build", "compile", "deploy", "docker build", "npm install", "pip install", "pytest")


class BackgroundError(Exception):
    """后台任务的领域异常，``error_code`` 是稳定的机器可读错误码。

    这是什么：后台任务系统的专用异常类
    Java 类比：自定义业务异常，携带错误码枚举
    为什么需要：区分不同失败原因（容量满、任务不存在、状态错误），让调用方精确处理
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code  # 稳定错误码，用于工具结果的 error_code 字段


def _uuid(value: str, label: str = "job_id") -> str:
    """校验 canonical UUID，防止任意字符串参与文件路径拼接。

    这是什么：UUID 格式校验工具函数
    Java 类比：类似 UUID.fromString(value) 会抛 IllegalArgumentException
    为什么需要：job_id 用于文件名拼接，必须是安全的 UUID 格式，防止路径穿越
    """
    if not isinstance(value, str) or CANONICAL_UUID.fullmatch(value) is None:
        raise BackgroundError("background_contract_error", f"{label} 必须是 canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class BackgroundJob:
    """后台 Job 的持久化快照。

    这是什么：后台任务的不可变状态记录
    Java 类比：不可变 record BackgroundJob(String id, String status, ToolResult result)
    为什么需要：封装任务状态，强制状态一致性规则（running 无 result，终态必须有 result）

    字段说明：
        id: canonical UUID，用于文件名和查询
        source_tool_call_id: 原始工具调用的 ID，用于事件回填时追溯上下文
        tool_name: 工具名称，用于日志和事件通知
        status: 6 种状态之一（见 STATUSES）
        result: 终态必须有结果，running 状态必须为 None
    """

    id: str
    source_tool_call_id: str
    tool_name: str
    status: str
    result: ToolResult | None

    def __post_init__(self) -> None:
        """构造后立即校验状态一致性，类似 Java record 的 compact constructor。"""
        _uuid(self.id)  # 校验 job_id 格式
        if not self.source_tool_call_id.strip() or not self.tool_name.strip():
            raise BackgroundError("background_contract_error", "工具调用 id 和工具名不能为空")
        if self.status not in STATUSES:  # 状态必须在枚举范围内
            raise BackgroundError("background_contract_error", "后台任务状态无效")

        # 状态一致性规则 1：running 状态不能携带 result（任务还在执行中）
        if self.status == "running" and self.result is not None:
            raise BackgroundError("background_contract_error", "running 状态不能携带 result")

        # 状态一致性规则 2：终态必须携带 result（任务已结束）
        if self.status != "running" and self.result is None:
            raise BackgroundError("background_contract_error", "终态必须携带 result")

        # 状态一致性规则 3：completed 必须是成功结果
        if self.status == "completed" and self.result is not None and self.result.is_error:
            raise BackgroundError("background_contract_error", "completed 必须是成功结果")

        # 状态一致性规则 4：失败终态（failed/timed_out/cancelled/interrupted）必须是错误结果
        if self.status != "completed" and self.status != "running" and self.result is not None and not self.result.is_error:
            raise BackgroundError("background_contract_error", "失败终态必须是错误结果")


class BackgroundJobStore(Protocol):
    """后台持久化接口，类似 Java Repository。

    这是什么：后台任务的持久化层接口
    Java 类比：interface BackgroundJobRepository { Job save(...); Job findById(...); }
    为什么需要：解耦领域逻辑与存储实现，测试时可以用内存实现替换文件实现
    """

    def create_running(self, job_id: str, source_tool_call_id: str, tool_name: str) -> BackgroundJob:
        """创建 running 状态的任务记录，返回持久化后的快照。"""
        ...

    def finish_running(self, job_id: str, status: str, result: ToolResult) -> BackgroundJob | None:
        """把 running 任务标记为终态，返回 None 表示任务已被外部删除或修改。"""
        ...

    def interrupt_running(self) -> tuple[BackgroundJob, ...]:
        """启动恢复时调用：把所有 running 标记为 interrupted，返回受影响的任务。"""
        ...

    def get_job(self, job_id: str) -> BackgroundJob:
        """查询单个任务，不存在时抛异常。"""
        ...

    def list_jobs(self) -> tuple[BackgroundJob, ...]:
        """列出所有任务（测试和调试用）。"""
        ...


class BackgroundOperation(Protocol):
    """后台线程实际执行的函数签名。

    这是什么：工具执行的函数接口
    Java 类比：@FunctionalInterface Callable<ToolResult>，但额外接收取消信号
    为什么需要：统一工具执行签名，让 operation 能感知 cancel_event 并提前退出
    """

    def __call__(self, cancel_event: threading.Event) -> ToolResult:
        """执行工具逻辑，返回 ToolResult。cancel_event.is_set() 表示外部请求取消。"""
        ...


@dataclass(frozen=True, slots=True)
class BackgroundJobEvent:
    """后台终态事件，供 EventInbox 注入主 Agent Loop。

    这是什么：后台任务完成时发布的事件
    Java 类比：record BackgroundJobEvent(...) implements RuntimeEvent
    为什么需要：当后台任务进入终态时，通过事件通知 Agent 循环，模型可以看到结果

    字段说明：
        event_id: 全局唯一事件 ID，用于去重（_seen_event_ids）
        job_id: 任务 ID，关联到原始任务记录
        source_tool_call_id: 原始工具调用 ID，模型可以追溯是哪个调用进入了后台
        tool_name: 工具名称，便于模型理解哪个工具完成了
        status: 终态状态（completed/failed/timed_out/cancelled/interrupted）
        result: 工具执行结果（成功或错误）
    """

    event_id: str
    job_id: str
    source_tool_call_id: str
    tool_name: str
    status: str
    result: ToolResult
    context_identity: str | None = None  # 预留字段：调用者身份
    idempotency_key: str | None = None  # 预留字段：幂等键

    def to_payload(self) -> Mapping[str, object]:
        """生成模型可见的稳定 JSON 字段。

        这是什么：把事件转换成模型可读的 JSON 结构
        Java 类比：toJson() 方法，返回 Map<String, Object>
        为什么需要：RuntimeEvent 注入历史时需要标准化的 payload 格式
        """
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "kind": "background_job",  # 事件类型标识，未来可能有其他 kind
            "result": {
                "content": self.result.content,
                "error_code": self.result.error_code,
                "is_error": self.result.is_error
            },
            "source_tool_call_id": self.source_tool_call_id,
            "status": self.status,
            "tool_name": self.tool_name,
        }


class JobSupervisor:
    """受控后台任务服务：容量、超时、取消、恢复、事件发布都集中在这里。

    这是什么：后台任务的线程池管理器
    Java 类比：类似 ExecutorService + ScheduledExecutorService 的组合
    为什么需要：统一管理后台线程的生命周期，避免无限制的并发和资源泄漏

    核心职责：
        1. 容量控制：最多同时运行 capacity 个任务
        2. 超时管理：单个任务执行超过 timeout 秒自动标记为 timed_out
        3. 取消支持：通过 cancel_event 通知 worker 停止
        4. 启动恢复：进程重启时把遗留 running 任务标记为 interrupted
        5. 事件发布：任务终态时发布事件到 EventInbox
    """

    def __init__(
        self,
        store: BackgroundJobStore,
        inbox: EventInbox,
        *,
        capacity: int = 4,  # 最大并发任务数，类似线程池大小
        timeout: float = 120.0,  # 单个任务超时秒数（默认 2 分钟）
        close_timeout: float = 10.0,  # 关闭时等待线程结束的超时秒数
        id_generator: Callable[[], str] | None = None,  # 测试用：可注入 UUID 生成器
        event_id_generator: Callable[[], str] | None = None  # 测试用：可注入事件 ID 生成器
    ) -> None:
        """初始化 Supervisor 并立即执行启动恢复。

        这是什么：构造器注入所有依赖
        Java 类比：类似 Spring @Autowired，但通过构造器注入而非字段注入
        为什么需要：依赖注入让测试时可以替换 store 和 inbox 实现
        """
        if capacity <= 0 or timeout <= 0 or close_timeout <= 0:
            raise ValueError("capacity 和 timeout 必须是正数")

        # 保存依赖
        self.store, self.inbox = store, inbox
        self.capacity, self.timeout, self.close_timeout = capacity, timeout, close_timeout
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))  # 默认生成 UUID v4
        self._event_id_generator = event_id_generator or (lambda: str(uuid.uuid4()))

        # 线程控制字典：job_id -> (Thread, Event)
        # Java 类比：ConcurrentHashMap<String, Pair<Thread, CountDownLatch>>
        self._controls: dict[str, tuple[threading.Thread, threading.Event]] = {}

        # 可重入锁：保护 _controls 的并发修改
        # Java 类比：ReentrantLock
        self._lock = threading.RLock()

        # 关闭标志：True 表示不再接受新任务
        self._closed = False

        # 恢复完成标志：True 表示启动恢复已执行
        self._ready = False

        # 立即执行启动恢复（把遗留 running 标记为 interrupted）
        self._recover()

    def _recover(self) -> None:
        """启动时把上次进程遗留的 running 标记成 interrupted，只通知一次。

        这是什么：进程启动时的恢复机制
        Java 类比：类似 @PostConstruct 初始化方法，在构造后自动执行
        为什么需要：上次进程可能异常退出，留下 running 孤儿任务，恢复时标记为 interrupted

        执行流程：
            1. 调用 store.interrupt_running() 把所有 running 标记为 interrupted
            2. 为每个受影响的任务发布 interrupted 事件
            3. 设置 _ready = True 表示恢复完成
        """
        for job in self.store.interrupt_running():
            if job.result is not None:  # 终态任务才发布事件
                self.inbox.publish(self._event(job))
        self._ready = True  # 标记恢复完成，防止重复执行

    def _event(self, job: BackgroundJob) -> BackgroundJobEvent:
        """从终态 Job 创建一个事件。

        这是什么：事件工厂方法
        Java 类比：private BackgroundJobEvent createEvent(BackgroundJob job)
        为什么需要：统一事件创建逻辑，确保 event_id 唯一
        """
        assert job.result is not None  # 终态任务必须有结果
        return BackgroundJobEvent(
            self._event_id_generator(),  # 生成唯一事件 ID
            job.id,
            job.source_tool_call_id,
            job.tool_name,
            job.status,
            job.result
        )

    @property
    def ready(self) -> bool:
        """返回恢复是否完成。

        这是什么：只读属性，检查启动恢复状态
        Java 类比：public boolean isReady() { return ready; }
        为什么需要：测试时可以确认恢复已完成，避免竞态条件
        """
        return self._ready

    @property
    def active_count(self) -> int:
        """返回当前受 Supervisor 管理的 worker 数量。

        这是什么：当前运行中的任务计数
        Java 类比：类似 ExecutorService.getActiveCount()
        为什么需要：用于容量检查（submit 时）和空闲等待（wait_idle）
        """
        with self._lock:  # 线程安全读取
            return len(self._controls)

    @property
    def has_pending_work(self) -> bool:
        """判断是否还有运行中的后台任务。

        这是什么：检查是否有待完成任务
        Java 类比：public boolean hasPendingTasks()
        为什么需要：Agent 循环在 stop 时检查是否需要等待后台任务完成
        """
        return self.active_count > 0

    def submit(self, source_tool_call_id: str, tool_name: str, operation: BackgroundOperation) -> str:
        """先容量检查、再落盘 running、最后启动 worker。

        这是什么：提交后台任务的入口方法
        Java 类比：public String submit(Callable<ToolResult> task) throws BackgroundError
        为什么需要：异步执行长时间工具，立即返回 job_id 给模型

        执行流程：
            1. 检查容量是否已满（_controls 数量 >= capacity）
            2. 生成 job_id 并持久化为 running 状态
            3. 创建 cancel_event 和 worker 线程
            4. 把线程控制加入 _controls 字典
            5. 启动线程并返回 job_id

        返回：job_id（UUID 字符串）
        异常：BackgroundError 当容量满或服务已关闭
        """
        with self._lock:  # 整个提交过程需要原子性
            # 检查服务是否已关闭
            if self._closed:
                raise BackgroundError("background_closed", "后台任务服务已关闭")

            # 容量检查：类似线程池的 maximumPoolSize
            if len(self._controls) >= self.capacity:
                raise BackgroundError("background_capacity", "后台任务容量已满")

            # 生成 job_id 并校验格式
            job_id = _uuid(self._id_generator())

            # 先持久化为 running 状态（类似 WAL，确保不丢失任务记录）
            self.store.create_running(job_id, source_tool_call_id, tool_name)

            # 创建取消信号：类似 Java 的 CountDownLatch 或 Future.cancel()
            cancel_event = threading.Event()

            # 创建守护线程：daemon=True 表示主进程退出时自动结束
            # 类似 Java 的 Thread.setDaemon(true)
            worker = threading.Thread(
                target=self._run_worker,
                args=(job_id, operation, cancel_event),
                daemon=True
            )

            # 记录线程控制对，便于后续 cancel 和 close
            self._controls[job_id] = (worker, cancel_event)

            # 启动线程（实际执行在后台进行）
            worker.start()

            return job_id  # 立即返回 job_id，不等待任务完成

    def _run_worker(self, job_id: str, operation: BackgroundOperation, cancel_event: threading.Event) -> None:
        """执行单个 worker，并通过条件迁移保证终态事件只发布一次。

        这是什么：后台线程的主执行逻辑
        Java 类比：private void runWorker(String jobId, Callable<ToolResult> operation)
        为什么需要：封装工具执行、超时检测、状态迁移、事件发布的完整流程

        状态迁移规则（按优先级）：
            1. operation() 执行成功且 result.is_error=False → completed
            2. operation() 执行成功但 result.is_error=True → failed
            3. operation() 抛异常 → failed
            4. cancel_event.is_set() → cancelled（优先级高于超时）
            5. time.monotonic() - started > timeout → timed_out

        执行流程：
            1. 记录开始时间（用于超时检测）
            2. 执行 operation(cancel_event)
            3. 根据结果和状态决定终态
            4. 持久化终态到 store
            5. 从 _controls 删除自己（释放槽位）
            6. 发布终态事件到 inbox
        """
        status, result = "completed", None  # 初始假设为成功
        started = time.monotonic()  # 记录开始时间（单调时钟，不受系统时间调整影响）

        try:
            # 调用实际工具逻辑（可能阻塞很长时间）
            result = operation(cancel_event)

            # 校验返回值类型
            if not isinstance(result, ToolResult):
                result = tool_error("background_contract_error", "后台操作返回了无效结果")

            # 如果工具返回错误结果，状态改为 failed
            if result.is_error:
                status = "failed"

        except Exception:  # noqa: BLE001  # 捕获所有异常，避免线程崩溃
            # 工具执行异常，标记为 failed
            status, result = "failed", tool_error("background_execution_error", "后台任务执行失败")

        # 状态修正 1：如果外部请求取消（通过 cancel() 或 close()），优先标记为 cancelled
        if cancel_event.is_set() and status == "completed":
            status, result = "cancelled", tool_error("background_cancelled", "后台任务已取消")

        # 状态修正 2：如果执行时间超过超时阈值，标记为 timed_out
        if time.monotonic() - started > self.timeout and status == "completed":
            status, result = "timed_out", tool_error("background_timeout", "后台任务执行超时")

        # 断言：此时 result 必须非 None（所有分支都赋值了）
        assert result is not None

        # 持久化终态：finish_running 返回 None 表示任务已被外部删除或修改
        job = self.store.finish_running(job_id, status, result)

        # 从控制字典删除自己（释放容量槽位）
        with self._lock:
            self._controls.pop(job_id, None)  # pop 不存在的 key 不报错

        # 只有持久化成功才发布事件（避免重复通知）
        if job is not None:
            self.inbox.publish(self._event(job))

    def cancel(self, job_id: str) -> BackgroundJob:
        """请求取消并等待 worker 收束，再返回最终持久化状态。

        这是什么：取消运行中任务的接口
        Java 类比：public BackgroundJob cancel(String jobId) throws BackgroundError
        为什么需要：让用户或模型能主动取消长时间运行的任务

        执行流程：
            1. 校验 job_id 格式
            2. 查找对应的 (Thread, Event) 控制对
            3. 设置 cancel_event（通知 worker 停止）
            4. 等待线程结束（最多 close_timeout 秒）
            5. 返回最终持久化状态

        返回：终态 BackgroundJob（status 可能是 cancelled 或其他）
        异常：BackgroundError 当任务已是终态或找不到
        """
        job_id = _uuid(job_id)  # 先校验格式

        # 查找控制对（需要加锁读取 _controls）
        with self._lock:
            control = self._controls.get(job_id)

        # 任务不在运行中
        if control is None:
            # 尝试从持久化读取任务状态
            job = self.store.get_job(job_id)

            # 如果任务已经是终态，报错
            if job.status != "running":
                raise BackgroundError("background_job_state", "任务已经是终态")

            # 任务是 running 但不在 _controls 中（异常情况）
            raise BackgroundError("background_job_not_found", "找不到正在运行的后台任务")

        # 设置取消信号（worker 会在下一次检查时感知）
        control[1].set()

        # 等待线程结束（最多 close_timeout 秒）
        # 类似 Java 的 Future.get(timeout, TimeUnit.SECONDS)
        control[0].join(self.close_timeout)

        # 返回最终状态（可能是 cancelled、completed、timed_out 等）
        return self.store.get_job(job_id)

    def get_job(self, job_id: str) -> BackgroundJob:
        """读取单个后台任务。

        这是什么：查询任务状态的接口
        Java 类比：public BackgroundJob getJob(String jobId)
        为什么需要：让模型通过 query_background_job 工具查询任务进度
        """
        return self.store.get_job(_uuid(job_id))

    def list_jobs(self) -> tuple[BackgroundJob, ...]:
        """读取全部后台任务。

        这是什么：列出所有任务的接口
        Java 类比：public List<BackgroundJob> listJobs()
        为什么需要：测试和调试时查看所有任务状态
        """
        return self.store.list_jobs()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """等待所有 worker 结束，返回是否在超时前完成。

        这是什么：阻塞等待所有任务完成的工具方法
        Java 类比：public boolean awaitTermination(long timeout, TimeUnit unit)
        为什么需要：测试时需要等待后台任务完成后再断言结果

        参数：
            timeout: 超时秒数，None 表示无限等待

        返回：True 表示所有任务完成，False 表示超时
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        # 循环检查是否还有运行中的任务
        while self.has_pending_work:
            # 检查是否超时
            if deadline is not None and time.monotonic() >= deadline:
                return False

            # 短暂休眠避免忙等（类似 Java 的 Thread.sleep(10)）
            time.sleep(0.01)

        return True  # 所有任务完成

    def close(self) -> None:
        """拒绝新任务，取消并等待已有 worker。

        这是什么：优雅关闭后台服务
        Java 类比：类似 ExecutorService.shutdown() + awaitTermination()
        为什么需要：进程退出前需要尝试完成或取消所有任务，避免数据丢失

        执行流程：
            1. 设置 _closed = True（拒绝新 submit）
            2. 获取所有 (Thread, Event) 控制对的快照
            3. 对所有控制对设置 cancel_event（通知 worker 停止）
            4. 等待所有线程结束（最多 close_timeout 秒）
        """
        # 加锁设置关闭标志，并获取控制对快照
        with self._lock:
            self._closed = True
            controls = tuple(self._controls.values())  # 快照，避免迭代时修改

        # 设置所有取消信号
        for _, event in controls:
            event.set()

        # 等待所有线程结束
        for thread, _ in controls:
            thread.join(self.close_timeout)  # 超时后放弃等待（线程继续运行但被标记为 interrupted）

    def drain_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """取走已完成事件。

        这是什么：非阻塞获取已发布事件
        Java 类比：public List<RuntimeEvent> drainEvents(int limit)
        为什么需要：Agent 循环在每轮开始时取出已完成事件注入历史
        """
        return self.inbox.drain(limit)

    def wait_for_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞等待完成事件。

        这是什么：阻塞等待新事件
        Java 类比：类似 BlockingQueue.take()
        为什么需要：Agent 循环在 stop 时如果有后台任务，等待至少一个事件到达
        """
        return self.inbox.wait(limit)


def should_run_in_background(command: str, requested: bool | None) -> bool:
    """实现 P13 三态规则：true 强制后台，false 强制同步，None 使用关键词启发式。

    这是什么：后台执行决策函数
    Java 类比：public static boolean shouldRunInBackground(String command, Boolean requested)
    为什么需要：支持三种模式：显式后台、显式同步、自动判断

    参数：
        command: 工具命令字符串（如 "npm install react"）
        requested: run_in_background 参数值
            - True: 强制后台执行
            - False: 强制同步执行
            - None: 根据 command 内容启发式判断

    返回：True 表示应该后台执行，False 表示应该同步执行

    启发式规则：
        如果 command 包含 BACKGROUND_MARKERS 中的任何关键词，返回 True
        例如："npm install" 包含 "npm install" → True
             "pytest tests/" 包含 "pytest" → True
             "ls -la" 不包含任何标记 → False
    """
    if requested is not None:
        return requested  # 显式指定时直接返回

    # 启发式识别：转小写后检查是否包含后台标记
    lowered = command.lower()
    return any(marker in lowered for marker in BACKGROUND_MARKERS)


class BackgroundDispatcher:
    """在权限检查之后，把可后台工具分流给 JobSupervisor。

    这是什么：工具分流器，决定工具是同步还是后台执行
    Java 类比：类似策略模式的 ToolExecutionStrategy 接口实现
    为什么需要：在 Agent 循环的 _execute_tool 中插入后台决策点，避免修改核心循环逻辑

    核心决策逻辑：
        1. 工具必须声明 concurrency="background_eligible"（白名单机制）
        2. 提取 run_in_background 参数和 command 参数
        3. 调用 should_run_in_background() 判断是否后台
        4. 后台执行：提交到 Supervisor，返回 job_id 作为 ToolResult
        5. 同步执行：返回 None，让 loop 继续调用 tools.invoke()
    """

    def __init__(self, supervisor: JobSupervisor) -> None:
        """注入 JobSupervisor 依赖。

        这是什么：构造器注入
        Java 类比：类似 @Autowired private final JobSupervisor supervisor
        为什么需要：Dispatcher 不负责管理线程，只负责分流决策
        """
        self.supervisor = supervisor

    def dispatch(self, prepared: PreparedToolCall, context: ToolContext, tools: ToolRegistry) -> ToolResult | None:
        """后台提交成功返回 running 占位结果；不适用时返回 None。

        这是什么：工具分流的核心方法，实现 ToolDispatcher 接口
        Java 类比：public ToolResult dispatch(PreparedToolCall prepared, ToolContext context)
        为什么需要：让 loop._execute_tool 在权限检查后、invoke 前插入后台决策

        返回值语义：
            - None: 表示"不处理，继续默认流程"（让 loop 调用 tools.invoke）
            - ToolResult: 表示"已处理，直接返回这个结果"（短路后续 invoke）

        分流条件（全部满足才后台执行）：
            1. definition 不为 None（工具定义存在）
            2. definition.concurrency == "background_eligible"（工具支持后台）
            3. prepared.arguments 不为 None（参数已解析）
            4. should_run_in_background() 返回 True（决策为后台）

        后台执行流程：
            1. 从 arguments 中 pop 出 run_in_background 参数（避免传给真实工具）
            2. 构造 operation lambda：调用 tools.invoke() 但传入修改后的 arguments
            3. 调用 supervisor.submit() 提交任务
            4. 返回成功 ToolResult，内容为 "后台任务已提交: job_id=xxx"
        """
        definition = prepared.definition

        # 前置条件检查：工具定义、并发标记、参数都必须存在
        if definition is None or definition.concurrency != "background_eligible" or prepared.arguments is None:
            return None  # 不满足后台条件，返回 None 让 loop 同步执行

        # 提取参数（需要修改，所以先复制一份）
        arguments = dict(prepared.arguments)

        # 提取 run_in_background 参数并从字典中删除（真实工具不需要这个参数）
        requested = arguments.pop("run_in_background", None)

        # 提取 command 参数用于启发式判断
        command = str(arguments.get("command", ""))

        # 决策：是否应该后台执行
        if not should_run_in_background(command, requested):
            return None  # 决策为同步，返回 None

        # 提交后台任务：构造 operation lambda
        # 注意：这里传入修改后的 arguments（已去除 run_in_background）
        job_id = self.supervisor.submit(
            prepared.call.id,  # 原始工具调用 ID
            definition.name,   # 工具名称
            lambda cancel: tools.invoke(
                PreparedToolCall(prepared.call, definition, arguments, None),
                context
            )
        )

        # 返回占位结果：告知模型任务已提交，后续通过事件获取真实结果
        return tool_success(f"后台任务已提交: job_id={job_id}; status=running")


def register_background_job_tools(registry: ToolRegistry, supervisor: JobSupervisor) -> None:
    """仅给 P13 主 Agent 注册查询和取消工具。

    这是什么：注册后台任务管理工具的工厂函数
    Java 类比：public static void registerTools(ToolRegistry registry, JobSupervisor supervisor)
    为什么需要：让模型能通过工具查询任务状态（query_background_job）和取消任务（cancel_background_job）

    注册的工具：
        1. query_background_job: 查询后台任务状态
        2. cancel_background_job: 取消正在运行的后台任务
    """
    # 参数校验函数：只接受 {"job_id": "uuid"} 格式
    def validate(value: Mapping[str, object]) -> bool:
        """校验工具参数：必须只有 job_id 字段，且格式为 canonical UUID。"""
        return (
            set(value) == {"job_id"}  # 只能有 job_id 一个字段
            and isinstance(value.get("job_id"), str)
            and CANONICAL_UUID.fullmatch(str(value["job_id"])) is not None
        )

    # query_background_job 工具处理器
    def query(arguments: Mapping[str, object], _: ToolContext) -> ToolResult:
        """查询后台任务状态，返回 JSON 格式的任务信息。"""
        try:
            job = supervisor.get_job(str(arguments["job_id"]))
            return tool_success(_job_text(job))  # 转换成 JSON 文本
        except BackgroundError as error:
            # 已知领域错误：任务不存在、格式错误等
            return tool_error(error.error_code, str(error))

    # cancel_background_job 工具处理器
    def cancel(arguments: Mapping[str, object], _: ToolContext) -> ToolResult:
        """取消运行中的后台任务，返回最终状态。"""
        try:
            return tool_success(_job_text(supervisor.cancel(str(arguments["job_id"]))))
        except BackgroundError as error:
            # 已知领域错误：任务已终态、找不到任务等
            return tool_error(error.error_code, str(error))

    # JSON Schema：定义工具参数结构
    schema = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
        "additionalProperties": False  # 不允许额外字段
    }

    # 注册查询工具
    registry.register(ToolDefinition(
        "query_background_job",
        "查询后台任务当前状态",
        schema,
        "read",  # 只读工具，不修改状态
        query,
        validate
    ))

    # 注册取消工具
    registry.register(ToolDefinition(
        "cancel_background_job",
        "取消正在运行的后台任务",
        schema,
        "write",  # 写工具，会修改任务状态
        cancel,
        validate
    ))


def _job_text(job: BackgroundJob) -> str:
    """把 Job 转换成适合模型阅读的 JSON 文本。

    这是什么：序列化 BackgroundJob 为 JSON 字符串
    Java 类比：public static String toJson(BackgroundJob job)
    为什么需要：工具结果必须是字符串，需要把结构化对象转换成 JSON 文本

    返回格式示例：
    {
        "job_id": "123e4567-e89b-12d3-a456-426614174000",
        "status": "completed",
        "tool_name": "run_shell",
        "source_tool_call_id": "call_abc123",
        "result": {
            "content": "命令执行成功",
            "error_code": null,
            "is_error": false
        }
    }
    """
    import json
    return json.dumps(
        {
            "job_id": job.id,
            "status": job.status,
            "tool_name": job.tool_name,
            "source_tool_call_id": job.source_tool_call_id,
            "result": None if job.result is None else {
                "content": job.result.content,
                "error_code": job.result.error_code,
                "is_error": job.result.is_error
            }
        },
        ensure_ascii=False  # 保留中文字符，不转义为 \uXXXX
    )
