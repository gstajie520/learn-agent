package learn.agent.llm.tool;

import learn.agent.llm.structured.SceneSnapshot;

/**
 * 程序提供给工具的受控运行环境。
 *
 * <p>为什么工具不能自己去拿它需要的东西：<b>因为那样就没有边界了</b>。</p>
 *
 * <p>如果 handler 内部直接 {@code new JdbcTemplate(...)} 或读全局静态变量，
 * 那么「这个工具能碰到哪些数据」就取决于它自己的代码，没人能从外部约束。
 * 换成由调用方显式传入上下文，边界就变成了<b>可控且可测</b>的：
 * 测试里传一个只有两台设备的快照，工具就只能看到这两台。</p>
 *
 * <p>Java 后端对这个模式应该很熟悉：等价于 Service 方法接收一个带租户 id、
 * 操作人和数据范围的上下文对象，而不是从 ThreadLocal 里到处捞。</p>
 *
 * <p>{@code identity} 现在只用于日志，但它是阶段 8 权限判断的入口 ——
 * 「谁在调这个工具」决定了该不该放行。本课先把字段留出来。</p>
 */
public class ToolContext {

    /** 发起本次调用的用户或 Agent 身份，用于审计。 */
    private final String identity;

    /**
     * 工具可以读取的场景状态。
     *
     * <p>直接复用第 3 课的 {@link SceneSnapshot}：它是<b>不可变</b>的，
     * 所以工具没有任何办法偷偷改掉场景 —— 这个保证来自类型本身，
     * 不依赖工具作者的自觉。</p>
     */
    private final SceneSnapshot scene;

    public ToolContext(String identity, SceneSnapshot scene) {
        if (identity == null || identity.trim().isEmpty()) {
            throw new IllegalArgumentException("identity 不能为空，工具调用必须可审计");
        }
        if (scene == null) {
            throw new IllegalArgumentException("scene 不能为空");
        }
        this.identity = identity.trim();
        this.scene = scene;
    }

    public String getIdentity() {
        return identity;
    }

    public SceneSnapshot getScene() {
        return scene;
    }

    @Override
    public String toString() {
        return "ToolContext{identity=" + identity + ", scene=" + scene + "}";
    }
}
