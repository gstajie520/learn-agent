package learn.agent.llm.tool;

/**
 * 一个工具的完整定义。
 *
 * <p>这个类同时服务两个读者，这一点很容易被忽略：
 * <ul>
 *   <li><b>模型</b>只看得到 {@code name}、{@code description}、{@code parametersSchema}。
 *       它靠这三样东西决定「要不要调用、传什么参数」。</li>
 *   <li><b>程序</b>看得到全部字段，尤其是 {@code effect}、{@code handler}、{@code validator}。
 *       这三样模型永远看不到，也不该看到。</li>
 * </ul>
 *
 * <p>换句话说：<b>描述是给模型看的，副作用等级是给人看的。</b>
 * 模型不知道某个工具会删数据，它只知道这个工具叫什么、干什么用。
 * 「这次删除要不要人工确认」是程序的判断，不是模型的判断 —— 因为一旦交给模型判断，
 * 提示词注入就能让它自己给自己批准。
 *
 * <p>字段全部 final：一个工具注册进去之后，它的语义不该在运行期被改写。
 */
public class ToolDefinition {

    /** 工具名。模型在 {@code tool_calls} 里回传的就是这个字符串。 */
    private final String name;

    /** 给模型看的说明。写得含糊，模型就会用错。 */
    private final String description;

    /** 参数的 JSON Schema 文本。发给模型时原样塞进请求。 */
    private final String parametersSchema;

    /** 副作用等级。决定「执行前要不要拦一道」。 */
    private final ToolEffect effect;

    /** 真正干活的实现。只有 {@link ToolRegistry#invoke} 会调它。 */
    private final ToolHandler handler;

    /** 业务校验器，可以为 null（表示这个工具没有 Schema 之外的约束）。 */
    private final ToolArgumentValidator validator;

    /**
     * @param name             工具名，只允许字母数字下划线（由 {@link ToolRegistry#register} 校验）
     * @param description      给模型的说明，不能为空
     * @param parametersSchema 参数 Schema 文本
     * @param effect           副作用等级
     * @param handler          执行实现
     * @param validator        业务校验器，允许为 null
     */
    public ToolDefinition(String name,
                          String description,
                          String parametersSchema,
                          ToolEffect effect,
                          ToolHandler handler,
                          ToolArgumentValidator validator) {
        this.name = name;
        this.description = description;
        this.parametersSchema = parametersSchema;
        this.effect = effect;
        this.handler = handler;
        this.validator = validator;
    }

    /**
     * 没有业务校验器的简化构造。
     *
     * <p>用它的场合：参数简单到 Schema 已经说完了全部约束。
     */
    public ToolDefinition(String name,
                          String description,
                          String parametersSchema,
                          ToolEffect effect,
                          ToolHandler handler) {
        this(name, description, parametersSchema, effect, handler, null);
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public String getParametersSchema() {
        return parametersSchema;
    }

    public ToolEffect getEffect() {
        return effect;
    }

    public ToolHandler getHandler() {
        return handler;
    }

    /** @return 业务校验器，可能为 null */
    public ToolArgumentValidator getValidator() {
        return validator;
    }

    /** @return 是否配了业务校验器 */
    public boolean hasValidator() {
        return validator != null;
    }

    @Override
    public String toString() {
        return "ToolDefinition{name='" + name + "', effect=" + effect.getWireValue()
                + ", hasValidator=" + hasValidator() + '}';
    }
}
