from pathlib import Path

import pytest

from agent_ch20.core.messages import tool_call
from agent_ch20.core.tools import ToolContext, ToolRegistry
from agent_ch20.features.skills import (
    DuplicateSkillError,
    SkillManifestError,
    SkillNameError,
    SkillNotFoundError,
    SkillPathError,
    SkillRegistry,
)


def write_skill(
    workspace: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str = "A test skill.",
    body: str = "# Test Skill\n\nprivate body\n",
) -> Path:
    skill_directory = workspace / "skills" / directory
    skill_directory.mkdir(parents=True, exist_ok=True)
    manifest = skill_directory / "SKILL.md"
    manifest.write_bytes(
        f"---\nname: {name or directory}\ndescription: {description}\n---\n{body}".encode()
    )
    return manifest


def test_missing_directory_produces_empty_catalog(tmp_path: Path) -> None:
    registry = SkillRegistry.scan(str(tmp_path))
    assert registry.names == ()
    assert registry.catalog_entries == ()
    assert registry.render_catalog() == ""


def test_catalog_is_sorted_bounded_and_does_not_expose_body(tmp_path: Path) -> None:
    write_skill(tmp_path, "zeta", description="Zeta", body="PRIVATE ZETA")
    write_skill(tmp_path, "alpha", description="Alpha", body="PRIVATE ALPHA")
    write_skill(tmp_path, "beta", description="Beta", body="PRIVATE BETA")

    registry = SkillRegistry.scan(str(tmp_path), max_catalog_entries=2, max_catalog_bytes=1_000)

    assert registry.names == ("alpha", "beta", "zeta")
    assert tuple(item.name for item in registry.catalog_entries) == ("alpha", "beta")
    assert registry.render_catalog() == "- **alpha**: Alpha\n- **beta**: Beta"
    assert "PRIVATE" not in registry.render_catalog()


def test_catalog_counts_utf8_bytes_without_partial_entry(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha", description="中文说明")
    write_skill(tmp_path, "beta", description="short")
    first_line = "- **alpha**: 中文说明"

    registry = SkillRegistry.scan(
        str(tmp_path), max_catalog_entries=10, max_catalog_bytes=len(first_line.encode("utf-8"))
    )

    assert registry.render_catalog() == first_line
    assert len(registry.render_catalog().encode("utf-8")) <= len(first_line.encode("utf-8"))


def test_load_skill_reads_body_only_after_explicit_tool_call(tmp_path: Path) -> None:
    body = "# Python Style\n\nUse pathlib.\n"
    write_skill(tmp_path, "python-style", description="Python project conventions", body=body)
    skills = SkillRegistry.scan(str(tmp_path))
    tools = ToolRegistry()
    tools.register(skills.tool_definition)

    prepared = tools.prepare(tool_call("skill-1", "load_skill", '{"name":"python-style"}'))
    result = tools.invoke(prepared, ToolContext(str(tmp_path), "tester"))

    assert result.content == body
    assert not result.is_error
    assert skills.render_catalog() == "- **python-style**: Python project conventions"
    assert skills.tool_definition.effect == "read"


def test_invalid_names_unknown_names_and_extra_arguments_are_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "known")
    skills = SkillRegistry.scan(str(tmp_path))
    tools = ToolRegistry()
    tools.register(skills.tool_definition)

    with pytest.raises(SkillNameError):
        skills.load_skill("../secret")
    with pytest.raises(SkillNotFoundError):
        skills.load_skill("missing")
    traversal = tools.invoke(
        tools.prepare(tool_call("escape", "load_skill", '{"name":"../secret"}')),
        ToolContext(str(tmp_path), "tester"),
    )
    extra = tools.invoke(
        tools.prepare(tool_call("extra", "load_skill", '{"name":"known","path":"secret"}')),
        ToolContext(str(tmp_path), "tester"),
    )
    assert traversal.error_code == "invalid_arguments"
    assert extra.error_code == "invalid_arguments"


def test_bad_frontmatter_name_mismatch_and_duplicate_names_fail(tmp_path: Path) -> None:
    (tmp_path / "skills" / "bad").mkdir(parents=True)
    (tmp_path / "skills" / "bad" / "SKILL.md").write_text(
        "---\nname: bad\ndescription: missing close\n", encoding="utf-8"
    )
    with pytest.raises(SkillManifestError):
        SkillRegistry.scan(str(tmp_path))

    (tmp_path / "skills").rename(tmp_path / "skills-old")
    write_skill(tmp_path, "directory", name="different")
    with pytest.raises(SkillManifestError):
        SkillRegistry.scan(str(tmp_path))

    (tmp_path / "skills").rename(tmp_path / "skills-old-2")
    write_skill(tmp_path, "first", name="shared")
    write_skill(tmp_path, "second", name="shared")
    with pytest.raises(DuplicateSkillError):
        SkillRegistry.scan(str(tmp_path))


@pytest.mark.parametrize(
    "manifest",
    [
        "name: alpha\ndescription: valid\n",
        "---\nname: [\n---\n",
        "---\n- name: alpha\n- description: valid\n---\n",
        "---\ndescription: valid\n---\n",
        "---\nname: alpha\n---\n",
        "---\nname: 7\ndescription: valid\n---\n",
        "---\nname: alpha\ndescription: 7\n---\n",
        '---\nname: alpha\ndescription: "   "\n---\n',
        "---\nname: alpha\ndescription: |\n  first\n  second\n---\n",
    ],
)
def test_malformed_frontmatter_is_rejected(tmp_path: Path, manifest: str) -> None:
    skill_dir = tmp_path / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(manifest, encoding="utf-8")
    with pytest.raises(SkillManifestError):
        SkillRegistry.scan(str(tmp_path))


def test_invalid_utf8_in_body_is_rejected_only_when_loading(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(
        b"---\nname: alpha\ndescription: valid\n---\n" + bytes([0xFF])
    )
    skills = SkillRegistry.scan(str(tmp_path))
    assert skills.render_catalog() == "- **alpha**: valid"
    with pytest.raises(SkillManifestError):
        skills.load_skill("alpha")


def test_workspace_mismatch_and_path_escape_are_structured_errors(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha")
    skills = SkillRegistry.scan(str(tmp_path))
    tools = ToolRegistry()
    tools.register(skills.tool_definition)
    other = tmp_path.parent / "other-ch07"
    other.mkdir()
    try:
        mismatch = tools.invoke(
            tools.prepare(tool_call("mismatch", "load_skill", '{"name":"alpha"}')),
            ToolContext(str(other), "tester"),
        )
        assert mismatch.error_code == "skill_workspace_mismatch"
    finally:
        other.rmdir()

    with pytest.raises(SkillPathError):
        SkillRegistry.scan(str(tmp_path), skills_directory="../outside")
    with pytest.raises(SkillPathError):
        SkillRegistry.scan(str(tmp_path), skills_directory="nul")


def test_registered_directory_replacement_is_rechecked(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha", body="SAFE")
    skills = SkillRegistry.scan(str(tmp_path))
    moved = tmp_path / "moved-alpha"
    (tmp_path / "skills" / "alpha").rename(moved)
    outside = tmp_path.parent / "outside-ch07-skill"
    outside.mkdir()
    write_manifest = outside / "SKILL.md"
    write_manifest.write_bytes(b"---\nname: alpha\ndescription: outside\n---\nSECRET")
    try:
        (tmp_path / "skills" / "alpha").symlink_to(outside, target_is_directory=True)
    except OSError:
        outside.joinpath("SKILL.md").unlink()
        outside.rmdir()
        pytest.skip("当前 Windows 环境不允许创建目录链接")
    try:
        with pytest.raises(SkillPathError):
            skills.load_skill("alpha")
        result = tools_result(skills, str(tmp_path))
        assert result.error_code == "skill_path_escape"
        assert "SECRET" not in result.content
    finally:
        outside.joinpath("SKILL.md").unlink(missing_ok=True)
        outside.rmdir()


def tools_result(skills: SkillRegistry, workspace: str):
    tools = ToolRegistry()
    tools.register(skills.tool_definition)
    return tools.invoke(
        tools.prepare(tool_call("escaped", "load_skill", '{"name":"alpha"}')),
        ToolContext(workspace, "tester"),
    )
