"""第十七章 CLI 在配置失败时不能提前创建 SQLite 状态。"""

import sys

from agent_ch17.cli import main


def test_missing_settings_fail_before_sqlite_state_is_created(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["agent-ch17", "--prompt", "测试任务"])
    assert main() == 2
    assert not (tmp_path / ".agent_tutorial").exists()
