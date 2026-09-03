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
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * DynamicPromptProvider 测试。
 */
class DynamicPromptProviderTest {

    @TempDir
    Path tempDir;

    private ToolRegistry toolRegistry;
    private JsonObject context;

    @BeforeEach
    void setUp() {
        toolRegistry = new ToolRegistry();
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "read",
                "读取数据",
                "{}",
                learn.agent.llm.tool.ToolEffect.READ,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "write",
                "写入数据",
                "{}",
                learn.agent.llm.tool.ToolEffect.WRITE,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));
        Map<String, JsonValue> contextMap = new HashMap<String, JsonValue>();
        contextMap.put("env", JsonValue.of("test"));
        context = JsonValue.of(contextMap);
    }

    @Test
    void shouldRenderPromptWithMinimalSetup() {
        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("You are an assistant.")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .build();

        String prompt = provider.render();

        assertThat(prompt).contains("## identity");
        assertThat(prompt).contains("You are an assistant.");
        assertThat(prompt).contains("## tools");
        assertThat(prompt).contains("- read");
        assertThat(prompt).contains("- write");
        assertThat(prompt).contains("## workspace");
        assertThat(prompt).contains(tempDir.toAbsolutePath().normalize().toString());
        assertThat(prompt).contains("context: {\"env\":\"test\"}");
    }

    @Test
    void shouldRenderPromptWithSkills() throws Exception {
        // 创建临时 skill 目录（使用默认的 "skills" 名称）
        Path skillsDir = tempDir.resolve("skills");
        Files.createDirectories(skillsDir);

        // 创建 analyze skill
        Path analyzeDir = skillsDir.resolve("analyze");
        Files.createDirectories(analyzeDir);
        Files.write(analyzeDir.resolve("SKILL.md"),
            "---\nname: analyze\ndescription: Analyze code\n---\nAnalyze skill content".getBytes());

        SkillRegistry skillRegistry = SkillRegistry.scan(tempDir.toString(), null);

        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("You are an assistant.")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .skillRegistry(skillRegistry)
                .build();

        String prompt = provider.render();

        assertThat(prompt).contains("## skills");
        assertThat(prompt).contains("analyze");
        assertThat(prompt).contains("Analyze code");
    }

    @Test
    void shouldRenderPromptWithMemory() throws Exception {
        MemoryStore store = new MemoryStore(tempDir);
        java.util.List<MemoryRecord> records = new java.util.ArrayList<MemoryRecord>();
        records.add(new MemoryRecord("user-bob", "User is Bob", learn.agent.llm.memory.MemoryType.USER, "Bob is the current user."));
        store.extend(records);

        // 使用简单的 selector
        learn.agent.llm.memory.MemorySelector selector = new learn.agent.llm.memory.MemorySelector() {
            @Override
            public String select(String query, String catalog) throws Exception {
                return "[\"user-bob\"]";
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

        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("You are an assistant.")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .memorySession(session)
                .build();

        String prompt = provider.render();

        assertThat(prompt).contains("## memory");
        assertThat(prompt).contains("user-bob");
        assertThat(prompt).contains("Bob is the current user.");
    }

    @Test
    void shouldReflectToolRegistryChanges() {
        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("identity")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .build();

        String prompt1 = provider.render();
        assertThat(prompt1).contains("- read");
        assertThat(prompt1).contains("- write");
        assertThat(prompt1).doesNotContain("- execute");

        // 动态添加工具
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "execute",
                "执行命令",
                "{}",
                learn.agent.llm.tool.ToolEffect.DESTRUCTIVE,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));

        String prompt2 = provider.render();
        assertThat(prompt2).contains("- read");
        assertThat(prompt2).contains("- write");
        assertThat(prompt2).contains("- execute");
    }

    @Test
    void shouldCacheAcrossMultipleRenders() {
        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("identity")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .build();

        assertThat(provider.cacheHits()).isEqualTo(0);

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(0);

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(1);

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(2);
    }

    @Test
    void shouldInvalidateCacheWhenStateChanges() {
        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("identity")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(context)
                .build();

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(0);

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(1);

        // 修改工具注册表
        toolRegistry.register(new learn.agent.llm.tool.ToolDefinition(
                "newTool",
                "新工具",
                "{}",
                learn.agent.llm.tool.ToolEffect.READ,
                (args, ctx) -> learn.agent.llm.tool.ToolExecutionResult.success("ok")
        ));

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(1); // 缓存未命中

        provider.render();
        assertThat(provider.cacheHits()).isEqualTo(2); // 新状态下的缓存命中
    }

    @Test
    void shouldRenderWithAllComponents() throws Exception {
        // 准备 skill 目录（使用默认的 "skills" 名称）
        Path skillsDir = tempDir.resolve("skills");
        Files.createDirectories(skillsDir);
        Path debugDir = skillsDir.resolve("debug");
        Files.createDirectories(debugDir);
        Files.write(debugDir.resolve("SKILL.md"),
            "---\nname: debug\ndescription: Debug issues\n---\nDebug skill content".getBytes());

        SkillRegistry skillRegistry = SkillRegistry.scan(tempDir.toString(), null);

        MemoryStore store = new MemoryStore(tempDir);
        java.util.List<MemoryRecord> records = new java.util.ArrayList<MemoryRecord>();
        records.add(new MemoryRecord("project-info", "Project details", learn.agent.llm.memory.MemoryType.PROJECT, "This is a test project."));
        store.extend(records);

        // 使用简单的 selector
        learn.agent.llm.memory.MemorySelector selector = new learn.agent.llm.memory.MemorySelector() {
            @Override
            public String select(String query, String catalog) throws Exception {
                return "[\"project-info\"]";
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
        session.beginTurn("debug the code");

        Map<String, JsonValue> contextMap = new HashMap<String, JsonValue>();
        contextMap.put("mode", JsonValue.of("debug"));

        DynamicPromptProvider provider = DynamicPromptProvider.builder()
                .identity("You are a debugging assistant.")
                .toolRegistry(toolRegistry)
                .workspace(tempDir.toString())
                .context(JsonValue.of(contextMap))
                .skillRegistry(skillRegistry)
                .memorySession(session)
                .build();

        String prompt = provider.render();

        // 验证所有 section 都存在
        assertThat(prompt).contains("## identity");
        assertThat(prompt).contains("You are a debugging assistant.");
        assertThat(prompt).contains("## tools");
        assertThat(prompt).contains("- read");
        assertThat(prompt).contains("## workspace");
        assertThat(prompt).contains("## skills");
        assertThat(prompt).contains("debug");
        assertThat(prompt).contains("## memory");
        assertThat(prompt).contains("project-info");
        assertThat(prompt).contains("context: {\"mode\":\"debug\"}");
    }
}
