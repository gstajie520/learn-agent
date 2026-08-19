# Python 章节共享环境

所有迁移章节共用 Python 虚拟环境和模型配置：

```text
python/
├─ .venv/       # 只创建一次
├─ .env         # 只配置一次
├─ ch01_agent/  # 第 1 章代码
├─ ch02_agent/  # 第 2 章代码（后续生成）
└─ ...
```

首次使用时，在 `python/` 目录创建环境：

```powershell
Set-Location 'E:\cj\study\learn-agent\python'
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
Copy-Item '.env.example' '.env'
```

之后每个章节只需要把当前章节安装到这一个环境中，不要重新创建 `.venv` 或 `.env`：

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.\ch01_agent[dev]'
& .\.venv\Scripts\python.exe -m pytest '.\ch01_agent\tests'
```

章节运行时会从当前目录向父目录查找 `.env`，因此 `python/.env` 可以被所有章节复用。
