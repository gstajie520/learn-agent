package learn.agent.llm.prompting;

import learn.agent.llm.memory.MemorySession;
import learn.agent.llm.skill.SkillRegistry;
import learn.agent.llm.tool.ToolRegistry;

import java.util.Objects;

/**
 * 动态提示词提供者（零参数适配器）。
 * 绑定运行态对象（ToolRegistry、SkillRegistry、MemorySession），
 * 暴露 render() 方法给 AgentRunner，每轮请求时读取最新状态。
 */
public class DynamicPromptProvider {

    private final String identity;
    private final ToolRegistry toolRegistry;
    private final String workspace;
    private final JsonObject context;
    private final SkillRegistry skillRegistry;
    private final MemorySession memorySession;
    private final DynamicPromptRenderer renderer;

    private DynamicPromptProvider(Builder builder) {
        this.identity = Objects.requireNonNull(builder.identity, "identity cannot be null");
        this.toolRegistry = Objects.requireNonNull(builder.toolRegistry, "toolRegistry cannot be null");
        this.workspace = Objects.requireNonNull(builder.workspace, "workspace cannot be null");
        this.context = Objects.requireNonNull(builder.context, "context cannot be null");
        this.skillRegistry = builder.skillRegistry;
        this.memorySession = builder.memorySession;
        this.renderer = new DynamicPromptRenderer();
    }

    /**
     * 渲染当前系统提示词。
     * 每次调用时从绑定的运行态对象读取最新状态。
     */
    public String render() {
        DynamicPromptRenderer.DynamicPromptRendererOptions options =
                new DynamicPromptRenderer.DynamicPromptRendererOptions(
                        identity,
                        toolRegistry,
                        workspace,
                        context,
                        skillRegistry,
                        memorySession
                );
        return renderer.render(options);
    }

    /**
     * 获取缓存命中次数（用于测试和观测）。
     */
    public int cacheHits() {
        return renderer.cacheHits();
    }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private String identity;
        private ToolRegistry toolRegistry;
        private String workspace;
        private JsonObject context;
        private SkillRegistry skillRegistry;
        private MemorySession memorySession;

        private Builder() {
        }

        public Builder identity(String identity) {
            this.identity = identity;
            return this;
        }

        public Builder toolRegistry(ToolRegistry toolRegistry) {
            this.toolRegistry = toolRegistry;
            return this;
        }

        public Builder workspace(String workspace) {
            this.workspace = workspace;
            return this;
        }

        public Builder context(JsonObject context) {
            this.context = context;
            return this;
        }

        public Builder skillRegistry(SkillRegistry skillRegistry) {
            this.skillRegistry = skillRegistry;
            return this;
        }

        public Builder memorySession(MemorySession memorySession) {
            this.memorySession = memorySession;
            return this;
        }

        public DynamicPromptProvider build() {
            return new DynamicPromptProvider(this);
        }
    }
}
