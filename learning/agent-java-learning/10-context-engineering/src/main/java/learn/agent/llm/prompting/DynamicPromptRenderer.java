package learn.agent.llm.prompting;

import learn.agent.llm.memory.MemorySession;
import learn.agent.llm.skill.SkillRegistry;
import learn.agent.llm.tool.ToolRegistry;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 动态系统提示词渲染器。
 *
 * 按固定顺序组装系统提示词：identity → tools → workspace → skills → memory。
 * 内置缓存：相同输入复用上次结果，避免重复字符串拼接。
 */
public class DynamicPromptRenderer {

    private String lastKey;
    private String lastPrompt;
    private int cacheHits = 0;

    /**
     * 获取缓存命中次数（用于测试和观测）。
     */
    public int cacheHits() {
        return cacheHits;
    }

    /**
     * 渲染动态系统提示词。
     *
     * @param options 渲染选项
     * @return 组装好的系统提示词
     */
    public String render(DynamicPromptRendererOptions options) {
        // 1. 校验输入
        String identity = normalizeIdentity(options.identity());
        if (options.tools() == null) {
            throw new IllegalArgumentException("tools cannot be null");
        }
        if (options.workspace() == null || options.workspace().trim().isEmpty()) {
            throw new IllegalArgumentException("workspace must be a non-empty string");
        }
        if (options.context() == null) {
            throw new IllegalArgumentException("context cannot be null");
        }

        // 2. 规范化并生成缓存键
        JsonObject context = options.context();
        String contextJson = context.toStableJson();
        List<String> tools = new ArrayList<>(options.tools().names());
        Path workspace = Paths.get(options.workspace()).toAbsolutePath().normalize();

        String skillCatalog = options.skills() == null ? "" : options.skills().renderCatalog();
        String memoryBody = options.memory() == null || options.memory().getSelected().isEmpty()
                ? ""
                : options.memory().renderSelected();

        // 生成缓存键（覆盖所有模型可见输入）
        String key = buildCacheKey(identity, contextJson, tools, workspace.toString(), skillCatalog, memoryBody);

        // 3. 检查缓存
        if (key.equals(lastKey) && lastPrompt != null) {
            cacheHits++;
            return lastPrompt;
        }

        // 4. 渲染各个 section
        List<String> sections = new ArrayList<>();

        // identity section
        sections.add("## identity\n" + identity + "\ncontext: " + contextJson);

        // tools section
        String toolCatalog = tools.isEmpty()
                ? "(none)"
                : tools.stream().map(name -> "- " + name).collect(Collectors.joining("\n"));
        sections.add("## tools\n" + toolCatalog);

        // workspace section
        sections.add("## workspace\n" + workspace);

        // skills section (可选)
        if (!skillCatalog.isEmpty()) {
            sections.add("## skills\n" + skillCatalog);
        }

        // memory section (可选)
        if (!memoryBody.isEmpty()) {
            sections.add("## memory\n" + memoryBody);
        }

        // 5. 组装最终 prompt
        String prompt = String.join("\n\n", sections);

        // 6. 更新缓存
        lastKey = key;
        lastPrompt = prompt;

        return prompt;
    }

    private String normalizeIdentity(String identity) {
        if (identity == null) {
            throw new IllegalArgumentException("identity cannot be null");
        }
        String normalized = identity.trim();
        if (normalized.isEmpty()) {
            throw new IllegalArgumentException("identity must not be empty");
        }
        return normalized;
    }

    private String buildCacheKey(String identity, String contextJson, List<String> tools,
                                  String workspace, String skillCatalog, String memoryBody) {
        // 构造包含所有模型可见输入的稳定键
        java.util.Map<String, JsonValue> keyMap = new java.util.HashMap<>();
        keyMap.put("identity", JsonValue.of(identity));
        keyMap.put("context", JsonValue.of(contextJson));
        keyMap.put("tools", JsonValue.of(tools.stream().map(JsonValue::of).collect(Collectors.toList())));
        keyMap.put("workspace", JsonValue.of(workspace));
        keyMap.put("skills", JsonValue.of(skillCatalog));
        keyMap.put("memory", JsonValue.of(memoryBody));
        return JsonObject.of(keyMap).toStableJson();
    }

    /**
     * 动态提示词渲染选项。
     */
    public static class DynamicPromptRendererOptions {
        private final String identity;
        private final ToolRegistry tools;
        private final String workspace;
        private final JsonObject context;
        private final SkillRegistry skills;
        private final MemorySession memory;

        public DynamicPromptRendererOptions(String identity, ToolRegistry tools, String workspace, JsonObject context,
                                            SkillRegistry skills, MemorySession memory) {
            this.identity = Objects.requireNonNull(identity, "identity cannot be null");
            this.tools = Objects.requireNonNull(tools, "tools cannot be null");
            this.workspace = Objects.requireNonNull(workspace, "workspace cannot be null");
            this.context = Objects.requireNonNull(context, "context cannot be null");
            this.skills = skills;
            this.memory = memory;
        }

        public DynamicPromptRendererOptions(String identity, ToolRegistry tools, String workspace, JsonObject context) {
            this(identity, tools, workspace, context, null, null);
        }

        public String identity() {
            return identity;
        }

        public ToolRegistry tools() {
            return tools;
        }

        public String workspace() {
            return workspace;
        }

        public JsonObject context() {
            return context;
        }

        public SkillRegistry skills() {
            return skills;
        }

        public MemorySession memory() {
            return memory;
        }
    }
}
