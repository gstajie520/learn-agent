# 第 1 章：Python Agent Loop

这是原 TypeScript 第 1 章的 Python 迁移版。代码按 Java 后端常见的分层组织：

```text
agent_ch01/
  core/       # 领域对象和核心接口，类似 Java 的 domain / service contract
  adapters/   # OpenAI、PowerShell 等外部系统适配器
  features/   # 具体工具定义
  bootstrap.py # 组合根：把实现装配成 AgentRunner
  cli.py       # 命令行入口
tests/        # 离线单元测试，不依赖真实模型
```

## 运行

首次准备共享环境（只执行一次）：

```powershell
Set-Location '.\python'
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
Copy-Item '.env.example' '.env'
```

安装本章节（后续章节复用同一个 `.venv` 和 `.env`）：

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.\ch01_agent[dev]'
```

编辑 `python/.env` 后运行：

```powershell
Set-Location '.\ch01_agent'
& ..\.venv\Scripts\python.exe -m agent_ch01.cli --prompt "列出当前目录"
```

真实运行会要求 PowerShell 工具调用授权。离线测试使用 FakeModelClient 和 FakeCommandRunner，不需要密钥或网络：

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
```

## Java 对照

`ModelClient` 类似 Java 的接口，`OpenAIChatModel` 是基础设施适配器，`ToolRegistry` 是命令注册表，`AgentRunner` 是核心应用服务，`build_agent` 是 Spring 配置类或 Composition Root。

## 小白阅读路线

不要从 `cli.py` 开始，也不要一次读完整个项目。第一次只追下面这一条调用链：

```text
tests/test_loop.py
  -> build_agent()
  -> AgentRunner.run()
  -> ModelClient.complete()
  -> ToolRegistry.prepare()
  -> ToolRegistry.invoke()
  -> ToolMessage 写回历史
  -> ModelClient.complete() 第二次调用
  -> 返回 final_text
```

### 第一步：只看一个测试

打开 `tests/test_loop.py`，找到：

```python
def test_loop_executes_tool_then_returns_final_text(tmp_path):
```

先不要研究所有 Python 语法，只看懂测试安排的故事：

```text
FakeModel 第一次说：请调用 shell
FakeCommandRunner 返回：42
FakeModel 第二次说：PowerShell 返回 42
AgentRunner 把最后一句话返回给测试
```

### 第二步：跳到 AgentRunner.run

在 IDEA 中把光标放到 `runner.run` 上，按 `Ctrl+B`。`run()` 是第一章最重要的方法。

遇到 Python 语法时，可以按下面的 Java 方式理解：

| Python | Java 中可以怎么理解 |
| --- | --- |
| `@dataclass` | Lombok `@Data` 或 Java `record` |
| `frozen=True` | 对象创建后字段不能修改 |
| `Protocol` | `interface` |
| `str | None` | `String` 允许为 `null` |
| `tuple[T, ...]` | 不可变的 `List<T>` |
| `self` | Java 的 `this`，但 Python 必须显式写出来 |
| `_name` | 约定这是内部字段，类似 `private`，但不是强制权限 |
| `*items` | 把集合元素展开，类似 `list.addAll(items)` |
| `**payload` | 把字典展开成关键字参数 |
| `with pytest.raises(...)` | JUnit `assertThrows(...)` |

### 第三步：分清接口和实现

先看接口，再看真实实现：

```text
core/model.py                 ModelClient 接口
adapters/openai_chat.py       DeepSeek/OpenAI 真实实现

core/commands.py              CommandRunner 接口
adapters/powershell.py        PowerShell 真实实现
tests/test_loop.py            两个接口的 Fake 实现
```

这和 Java 项目中的分层完全相同：Service 依赖接口，生产环境注入真实 Bean，单元测试注入 Fake。

### 第四步：阅读工具注册表

`ToolRegistry` 分成两步，不要混在一起理解：

```text
prepare = 找工具 + 解析 JSON + 校验参数，不执行副作用
invoke  = 真正调用 handler，可能启动 PowerShell
```

第一遍只需要记住：模型给出的参数是不可信字符串，程序必须先校验，确认安全后才执行。

## 每个文件只回答四个问题

阅读时在纸上记录：

1. 这个文件在 Java 项目中相当于哪一层？
2. 它接收什么输入？
3. 它返回什么输出？
4. 它把异常交给谁处理？

暂时不要背 Python 语法，也不要阅读 OpenAI SDK 内部源码。先理解对象之间如何合作，再补语言细节。
