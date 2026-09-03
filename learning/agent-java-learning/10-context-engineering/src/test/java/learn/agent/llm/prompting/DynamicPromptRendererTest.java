package learn.agent.llm.prompting;

import learn.agent.llm.memory.MemoryRecord;
import learn.agent.llm.memory.MemorySession;
import learn.agent.llm.memory.MemoryStore;
import learn.agent.llm.skill.SkillRegistry;
import learn.agent.llm.tool.ToolRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * DynamicPromptRenderer 测试。
 */
class DynamicPromptRendererTest {

    private DynamicPromptRenderer renderer;
    private ToolRegistry toolRegistry;
    private JsonObject emptyContext;

    @TempDir
    Path tempDir;

    @BeforeEach
    void setUp() {
        renderer = new DynamicPromptRenderer();
        toolRegistry = new ToolRegistry();
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "tool1",
                "测试工具1",
                "{}",
                learn.agent.llm.tool.ToolEffect.READ,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "tool2",
                "测试工具2",
                "{}",
                learn.agent.llm.tool.ToolEffect.READ,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));
        emptyContext = JsonValue.of(java.util.Collections.emptyMap());
    }

    @Test
    void shouldRenderMinimalPrompt() {
        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "You are a helpful assistant.",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext
                );

        String prompt = renderer.render(options);

        assertThat(prompt).contains("## identity");
        assertThat(prompt).contains("You are a helpful assistant.");
        assertThat(prompt).contains("## tools");
        assertThat(prompt).contains("- tool1");
        assertThat(prompt).contains("- tool2");
        assertThat(prompt).contains("## workspace");
        assertThat(prompt).contains(tempDir.toAbsolutePath().normalize().toString());
        assertThat(prompt).doesNotContain("## skills");
        assertThat(prompt).doesNotContain("## memory");
    }

    @Test
    void shouldIncludeContext() {
        java.util.Map<String, JsonValue> contextMap = new java.util.HashMap<String, JsonValue>();
        contextMap.put("user", JsonValue.of("alice"));
        contextMap.put("role", JsonValue.of("admin"));
        JsonObject context = JsonValue.of(contextMap);

        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity text",
                        toolRegistry,
                        tempDir.toString(),
                        context
                );

        String prompt = renderer.render(options);

        assertThat(prompt).contains("context: {\"role\":\"admin\",\"user\":\"alice\"}");
    }

    @Test
    void shouldIncludeSkillsWhenProvided() throws Exception {
        // 创建临时 skill 目录（使用默认的 "skills" 名称）
        Path skillsDir = tempDir.resolve("skills");
        Files.createDirectories(skillsDir);

        // 创建 skill1
        Path skill1Dir = skillsDir.resolve("skill1");
        Files.createDirectories(skill1Dir);
        Files.write(skill1Dir.resolve("SKILL.md"),
            "---\nname: skill1\ndescription: Does something\n---\nSkill content 1".getBytes());

        // 创建 skill2
        Path skill2Dir = skillsDir.resolve("skill2");
        Files.createDirectories(skill2Dir);
        Files.write(skill2Dir.resolve("SKILL.md"),
            "---\nname: skill2\ndescription: Does another thing\n---\nSkill content 2".getBytes());

        SkillRegistry skillRegistry = SkillRegistry.scan(tempDir.toString(), null);

        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext,
                        skillRegistry,
                        null
                );

        String prompt = renderer.render(options);

        assertThat(prompt).contains("## skills");
        assertThat(prompt).contains("skill1");
        assertThat(prompt).contains("Does something");
        assertThat(prompt).contains("skill2");
        assertThat(prompt).contains("Does another thing");
    }

    @Test
    void shouldIncludeMemoryWhenProvided() throws Exception {
        MemoryStore store = new MemoryStore(tempDir);
        java.util.List<MemoryRecord> records = new java.util.ArrayList<MemoryRecord>();
        records.add(new MemoryRecord("user-alice", "User is Alice", learn.agent.llm.memory.MemoryType.USER, "Alice is the user."));
        records.add(new MemoryRecord("pref-testing", "Prefers TDD", learn.agent.llm.memory.MemoryType.FEEDBACK, "Always write tests first."));
        store.extend(records);

        // 使用简单的 selector 直接返回所有记忆名称
        learn.agent.llm.memory.MemorySelector selector = new learn.agent.llm.memory.MemorySelector() {
            @Override
            public String select(String query, String catalog) throws Exception {
                return "[\"user-alice\", \"pref-testing\"]";
            }
        };

        MemorySession session = new MemorySession(
            store,
            selector,
            null,  // extractor
            null,  // consolidator
            10,    // maxSelected
            50,    // consolidateThreshold
            false  // emitContextMessages
        );
        session.beginTurn("test query");

        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext,
                        null,
                        session
                );

        String prompt = renderer.render(options);

        assertThat(prompt).contains("## memory");
        assertThat(prompt).contains("user-alice");
        assertThat(prompt).contains("Alice is the user.");
        assertThat(prompt).contains("pref-testing");
        assertThat(prompt).contains("Always write tests first.");
    }

    @Test
    void shouldCacheIdenticalInputs() {
        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext
                );

        assertThat(renderer.cacheHits()).isEqualTo(0);

        String prompt1 = renderer.render(options);
        assertThat(renderer.cacheHits()).isEqualTo(0);

        String prompt2 = renderer.render(options);
        assertThat(renderer.cacheHits()).isEqualTo(1);
        assertThat(prompt2).isSameAs(prompt1); // 完全相同的引用

        String prompt3 = renderer.render(options);
        assertThat(renderer.cacheHits()).isEqualTo(2);
        assertThat(prompt3).isSameAs(prompt1);
    }

    @Test
    void shouldInvalidateCacheWhenInputsChange() {
        DynamicPromptRenderer.DynamicPromptRendererOptions options1 =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity1",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext
                );

        DynamicPromptRenderer.DynamicPromptRendererOptions options2 =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity2",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext
                );

        renderer.render(options1);
        assertThat(renderer.cacheHits()).isEqualTo(0);

        renderer.render(options2);
        assertThat(renderer.cacheHits()).isEqualTo(0); // 缓存未命中

        renderer.render(options2);
        assertThat(renderer.cacheHits()).isEqualTo(1); // 缓存命中
    }

    @Test
    void shouldRejectNullIdentity() {
        assertThatThrownBy(() -> new DynamicPromptRenderer.DynamicPromptRendererOptions(
                null,
                toolRegistry,
                tempDir.toString(),
                emptyContext
        )).isInstanceOf(NullPointerException.class);
    }

    @Test
    void shouldRejectEmptyIdentity() {
        assertThatThrownBy(() -> renderer.render(
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "   ",
                        toolRegistry,
                        tempDir.toString(),
                        emptyContext
                )
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must not be empty");
    }

    @Test
    void shouldRejectNullTools() {
        assertThatThrownBy(() -> new DynamicPromptRenderer.DynamicPromptRendererOptions(
                "identity",
                null,
                tempDir.toString(),
                emptyContext
        )).isInstanceOf(NullPointerException.class);
    }

    @Test
    void shouldRejectNullWorkspace() {
        assertThatThrownBy(() -> new DynamicPromptRenderer.DynamicPromptRendererOptions(
                "identity",
                toolRegistry,
                null,
                emptyContext
        )).isInstanceOf(NullPointerException.class);
    }

    @Test
    void shouldRejectEmptyWorkspace() {
        assertThatThrownBy(() -> renderer.render(
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity",
                        toolRegistry,
                        "   ",
                        emptyContext
                )
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must be a non-empty string");
    }

    @Test
    void shouldRejectNullContext() {
        assertThatThrownBy(() -> new DynamicPromptRenderer.DynamicPromptRendererOptions(
                "identity",
                toolRegistry,
                tempDir.toString(),
                null
        )).isInstanceOf(NullPointerException.class);
    }

    @Test
    void shouldNormalizeWorkspacePath() {
        Path subDir = tempDir.resolve("subdir");
        String unnormalizedPath = subDir.toString() + "/../subdir";

        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        "identity",
                        toolRegistry,
                        unnormalizedPath,
                        emptyContext
                );

        String prompt = renderer.render(options);

        assertThat(prompt).contains(subDir.toAbsolutePath().normalize().toString());
    }
}
