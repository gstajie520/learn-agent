# 第 3 章：Agent 权限策略

本章是 TypeScript 第 3 章的 Python 完整迁移版。它在第二章的工作区文件工具之上增加 `PermissionPolicy`，把工具执行前的权限决定、人工审批和审计集中到一个策略服务中。

```text
agent_ch03/
  core/permissions.py     # 四态决定、规则、审批/审计 Protocol、策略合并
  core/loop.py            # 只有权限最终 allow 才调用工具 handler
  adapters/filesystem.py  # 同时提供写路径边界检查
  bootstrap.py            # P03 强制装配审批器和审计器
  cli.py                  # 终端审批与中文审计日志
tests/                    # 离线权限和累计行为测试
```

共享环境继续使用 `python/.venv` 和 `python/.env`，不会创建章节私有环境：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch03_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
```

先看 `tests/test_permissions.py`，再看 `core/permissions.py`，最后看 `core/loop.py` 如何把最终决定接到工具执行前。Java 对照：`PermissionPolicy` 类似应用服务，`PermissionRule` 类似策略规则 DTO，`ApprovalProvider` 和 `AuditSink` 是接口，`bootstrap.py` 是 Spring 配置类。
