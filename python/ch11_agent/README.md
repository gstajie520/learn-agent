# 第 11 章：模型 API 恢复策略（Python 版）

本章在第十章动态 Prompt、记忆和上下文压缩的基础上，增加一层“模型请求恢复层”。
它专门处理三类真实生产故障：输出被截断、输入超过上下文窗口、429/529 瞬态 API 错误。

## Java 开发者阅读顺序

建议按下面顺序考古，先看测试，再看实现：

| Python 文件 | Java 类比 | 先理解什么 |
| --- | --- | --- |
| `tests/test_recovery.py` | Mockito 参数化单测 | 每种故障预期重试几次、请求如何变化 |
| `agent_ch11/features/recovery.py` | Resilience Service / 拦截器 | 一次逻辑请求内部如何升级、续写、压缩和退避 |
| `agent_ch11/core/model.py` | Java interface + 自定义异常 | 内部统一模型请求和错误类型 |
| `agent_ch11/adapters/openai_chat.py` | 第三方 SDK Adapter | 把 OpenAI/DeepSeek 错误转换成内部异常 |
| `agent_ch11/core/loop.py` | 应用服务 | 外层 Agent Loop 只调用一次 executor |
| `agent_ch11/bootstrap.py` | Spring `@Configuration` | 依赖如何组装，哪些请求使用 raw model |
| `tests/test_ch11_integration.py` | `@SpringBootTest` | 真实章节装配后的完整行为 |

## Java 对照

- `@dataclass(frozen=True)` 类似 Java `record`，保存不可变配置或请求 DTO。
- `Protocol` 类似 Java `interface`，`ModelClient` 不关心 DeepSeek SDK 的具体类。
- `RecoveryManager` 类似包在 HTTP Client 外面的 resilience service。
- `CancellationToken` 类似 `AtomicBoolean` 加监听器集合。
- `build_agent()` 类似 Spring 组合根，负责构造对象，不负责业务循环。

## 运行环境

所有章节共享父目录的虚拟环境和 `.env`，不要每章重复创建：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch11_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
```

`.env` 位于 `python/.env`，第 11 章及以后必须包含：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=deepseek-chat
OPENAI_FALLBACK_MODEL=deepseek-reasoner
```

运行真实 Agent：

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch11.cli --prompt "检查当前工作区并给出结论"
```

## 三种故障和三条恢复路径

| 故障 | 内部信号 | 恢复动作 |
| --- | --- | --- |
| 输出被截断 | `finish_reason == "length"` | 第一次把 8000 提升到 64000；仍截断时在局部请求快照中续写 |
| 输入过长 | `ModelPromptTooLongError` | 保留首条 system message，响应式压缩一次 |
| 临时故障 | `ModelRateLimitError` / `ModelOverloadedError` | Retry-After、指数退避；连续 3 次 529 切换 fallback |

三条路径都由 `RecoveryManager.complete()` 负责。一次内部重试不会重新执行 UserPrompt Hook、工具执行或 Stop Hook，也不会增加外层 Agent turn。

## 1. 先把供应商错误归一化

适配器只读取 SDK 的结构化字段，不用 `"429" in str(error)` 这种脆弱判断：

```python
try:
    response = client.chat.completions.create(**payload)
except APIStatusError as error:
    mapped = _map_api_status_error(error)
    if mapped is None:
        raise
    raise mapped from error
```

映射规则是固定的：429 变成 `ModelRateLimitError`，529 变成 `ModelOverloadedError`，400 且错误码属于上下文长度集合时变成 `ModelPromptTooLongError`。未知状态、连接错误和程序错误原样抛出。

这就是 Java 中“Adapter 层把第三方异常转换成领域异常”的做法。核心层不应该到处依赖 OpenAI SDK 的字段名。

## 2. 输出截断：升级预算，再在请求快照中续写

`length` 是一次合法响应，不等于网络错误。第一次截断时丢弃半截回答，并把预算从 8000 提升到 64000：

```python
if reply.finish_reason == "length" and not state.has_escalated:
    state.current_max_tokens = config.escalated_max_tokens
    state.has_escalated = True
    continue
```

第二次仍截断，才追加非空纯文本片段和续写提示。追加发生在局部 `request_messages`，不会修改 `AgentRunner` 的 canonical history：

```python
fragments.append(fragment)
request_messages = (
    *request_messages,
    reply.message,
    user_message(CONTINUATION_PROMPT),
)
```

成功后只返回一个合并后的 `ModelReply`，所以外层历史只保存最终完整回答。带未完成 `tool_calls` 的截断响应会直接失败，避免产生孤儿工具调用。

## 3. 输入过长：保留 system，响应式压缩一次

输入过长不是 `length`。恢复层捕获 `ModelPromptTooLongError`，把首条 system prompt 与其余消息分开，调用第八章的 `CompactionManager`：

```python
leading, compactable = _split_leading_system(request_messages)
outcome = compaction.compact_on_prompt_too_long(
    compactable,
    retry_count=prompt_too_long_retries,
)
request_messages = (*leading, *outcome.history)
```

同一逻辑请求只允许压缩一次。摘要请求使用 raw `ModelClient`，不能再套 `RecoveryManager`，否则会出现“输入过长 -> 摘要 -> 输入过长”的递归。

响应式 transcript 记录的是压缩前请求快照。摘要失败时会删除刚写入的 transcript，避免工作区留下没有摘要的假 artifact。

## 4. 429、529、Retry-After 和 fallback

429 优先遵守 `Retry-After`，支持非负秒数和带时区的 RFC HTTP-date；没有该头时使用指数退避：

```text
delay = min(base_delay * 2**attempt, max_delay) + random(0..base_delay*25%)
```

等待如果会达到总 deadline，就直接抛出 `RecoveryDeadlineExceeded`，不睡到超时再报错。429 或成功会清零连续 529 计数；只有连续三次 529 才切换到 fallback 模型。

## 5. 取消与总时限

```python
token = CancellationToken()
token.cancel()                 # 幂等
unsubscribe = token.subscribe(listener)
unsubscribe()
```

恢复层会在每次模型请求前后、退避等待前后、响应式压缩前后检查取消和 deadline。Python 当前 `ModelClient.complete()` 是同步接口，因此不能像 TypeScript `AbortSignal` 那样强制中止已经运行中的同步 SDK 调用；只能在调用边界和可取消的等待阶段及时失败。文档明确这个差异，避免把“检查取消”误解成“能杀掉底层线程”。

## 6. 接入 Agent Loop

`AgentRunner` 增加一个类似 Java interface 的 `ModelRequestExecutor`：

```python
class ModelRequestExecutor(Protocol):
    def begin_turn(self) -> None: ...
    def complete(self, request: ModelRequest) -> ModelReply: ...
```

第 1 到第 10 章没有恢复能力，继续直接调用 raw model。第 11 章 Bootstrap 才创建 `RecoveryManager`，并强制传入 `RecoveryConfig`。恢复层只包装主循环请求；记忆 selector/extractor、压缩摘要和子 Agent 继续使用 raw model。

## 7. 学习方式

1. 先运行 `tests/test_recovery.py`，每次只读一个失败分支。
2. 在 `RecoveryManager.complete()` 设置断点，观察 `request_messages` 和 `RecoveryState` 的变化。
3. 回到 `core/loop.py`，确认外层只调用一次 `executor.complete()`。
4. 最后阅读 `adapters/openai_chat.py`，理解供应商异常为什么不能泄漏到核心层。

## 验证命令

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch11
& ..\.venv\Scripts\python.exe -m ruff check agent_ch11 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch11 --no-incremental
```

本章离线验证不需要真实密钥或网络。真实 DeepSeek smoke test 只有在 `.env` 完整且允许联网时才运行；否则以离线测试结果为准。
