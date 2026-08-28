package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import learn.agent.llm.lesson03.ValidationResult;

/**
 * 工具注册表：模型能调用哪些工具，由这个类说了算，不由模型说了算。
 *
 * <p>整个类只有两个对外的动作，而且<b>刻意分成两步</b>：
 * <ol>
 *   <li>{@link #prepare} —— 查工具、解析参数、跑校验。<b>零副作用</b>。
 *       无论模型给的东西多离谱，这一步只会返回一个 {@link PreparedToolCall}，不抛异常。</li>
 *   <li>{@link #invoke} —— 真正执行。<b>这是全类唯一会产生副作用的地方</b>。</li>
 * </ol>
 *
 * <p>为什么非要分开？因为「这次调用合不合法」和「这次调用要不要执行」是两个决定，
 * 而后者往往需要人参与：{@link ToolEffect#DESTRUCTIVE} 的工具在 prepare 之后、
 * invoke 之前，正好是插入二次确认的位置。如果解析和执行写在一个方法里，
 * 你就没有任何地方可以「先看清楚再决定」。
 *
 * <p>Java 8 写法：不用 record、不用 Optional 做字段、不用 var。
 */
public class ToolRegistry {

    /** 工具名的合法字符集。和 Python 版 {@code [A-Za-z0-9_]+} 保持一致。 */
    private static final Pattern NAME_PATTERN = Pattern.compile("[A-Za-z0-9_]+");

    /** 复用一个 mapper：Jackson 的 ObjectMapper 是线程安全的，没必要每次 new。 */
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 用 LinkedHashMap 而不是 HashMap：注册顺序 == 给模型看的顺序。
     * 顺序稳定，prompt 才稳定，缓存命中率和可复现性才有保障。
     */
    private final Map<String, ToolDefinition> tools = new LinkedHashMap<String, ToolDefinition>();

    /**
     * 注册一个工具。所有校验都在这里做完，宁可启动时就崩，也不要等模型调用时才发现工具名有问题。
     *
     * @throws IllegalArgumentException 名字非法、描述为空、或重复注册
     */
    public void register(ToolDefinition definition) {
        if (definition == null) {
            throw new IllegalArgumentException("definition 不能为 null");
        }
        String name = definition.getName();
        if (name == null || !NAME_PATTERN.matcher(name).matches()) {
            // 工具名会被拼进 JSON 发给模型，也会被模型原样回传。
            // 允许空格或中文，出问题时你分不清是模型抄错了还是你自己写错了。
            throw new IllegalArgumentException("工具名只能是字母数字下划线，当前是：" + name);
        }
        String description = definition.getDescription();
        if (description == null || description.trim().isEmpty()) {
            // 描述是模型选工具的唯一依据。描述为空 == 让模型抽签。
            throw new IllegalArgumentException("工具 " + name + " 缺少描述");
        }
        if (definition.getHandler() == null) {
            throw new IllegalArgumentException("工具 " + name + " 缺少 handler");
        }
        if (tools.containsKey(name)) {
            // 静默覆盖是最难查的 bug：两处注册同名工具，行为取决于类加载顺序。
            throw new IllegalArgumentException("工具名重复注册：" + name);
        }
        tools.put(name, definition);
    }

    /**
     * 这一轮模型能看到的工具清单（不可修改的副本）。
     *
     * <p>返回副本而不是内部 map：模型这一轮看到哪些工具，就必须只能执行这些工具。
     * 如果调用方能拿到可变引用，就可能在「发出去」和「执行」之间偷偷改动清单。
     */
    public Map<String, ToolDefinition> snapshot() {
        return Collections.unmodifiableMap(new LinkedHashMap<String, ToolDefinition>(tools));
    }

    /** 按注册顺序列出工具名，主要给日志和测试用。 */
    public List<String> names() {
        return Collections.unmodifiableList(new ArrayList<String>(tools.keySet()));
    }

    public int size() {
        return tools.size();
    }

    /**
     * 第一步：把模型的一次 {@link ToolCall} 变成一个「已判定」的 {@link PreparedToolCall}。
     *
     * <p><b>这个方法不抛异常，也不执行任何工具。</b>四种失败全部变成 error 态的返回值：
     * <ul>
     *   <li>{@code tool_not_found} —— 模型编了一个不存在的工具名</li>
     *   <li>{@code invalid_arguments_json} —— arguments 不是合法 JSON</li>
     *   <li>{@code arguments_not_object} —— 是合法 JSON，但是数组/字符串/数字</li>
     *   <li>{@code invalid_arguments} —— 结构对，但业务校验不通过</li>
     * </ul>
     * 全都变成返回值，是为了让上层的循环只有一条主路径：prepare 完直接 invoke，
     * 不需要 try/catch，也不需要判断「这是失败还是成功」再分叉。
     */
    public PreparedToolCall prepare(ToolCall call) {
        if (call == null) {
            throw new IllegalArgumentException("call 不能为 null");
        }

        // 1) 查表。模型完全有能力返回一个你从没注册过的名字。
        ToolDefinition definition = tools.get(call.getName());
        if (definition == null) {
            return PreparedToolCall.failed(call, null,
                    ToolExecutionResult.error("tool_not_found",
                            "未注册的工具：" + call.getName() + "；可用工具：" + names()));
        }

        // 2) 解析 arguments。模型给的是一个「字符串」，里面装着 JSON——
        //    也就是说这里有两层，字符串这层永远合法，JSON 那层随时可能不合法。
        String raw = call.getRawArguments();
        JsonNode arguments;
        if (raw == null || raw.trim().isEmpty()) {
            // 无参工具很常见，模型可能给 ""、也可能给 "{}"，两种都当空对象处理。
            arguments = JsonNodeFactory.instance.objectNode();
        } else {
            try {
                arguments = MAPPER.readTree(raw);
            } catch (Exception e) {
                // 注意：这里吞掉异常是刻意的。模型输出不合法是<b>预期内</b>的事件，
                // 不是程序 bug，所以它应该变成一条能回传给模型的错误消息。
                return PreparedToolCall.failed(call, definition,
                        ToolExecutionResult.error("invalid_arguments_json",
                                "arguments 不是合法 JSON：" + e.getMessage()));
            }
        }

        // 3) 必须是对象。{"x":1} 才能按字段取值，[1,2] 不行。
        if (!arguments.isObject()) {
            return PreparedToolCall.failed(call, definition,
                    ToolExecutionResult.error("arguments_not_object",
                            "arguments 必须是 JSON 对象，实际是：" + arguments.getNodeType()));
        }

        // 4) 工具自己的校验。复用第 3 课的 ValidationResult，错误信息可以一次性收集多条。
        if (definition.hasValidator()) {
            ValidationResult<JsonNode> result = definition.getValidator().validate(arguments);
            if (!result.isValid()) {
                return PreparedToolCall.failed(call, definition,
                        ToolExecutionResult.error("invalid_arguments", result.getErrorMessage()));
            }
        }

        return PreparedToolCall.ready(call, definition, arguments);
    }

    /**
     * 第二步：执行。<b>全类唯一有副作用的方法。</b>
     *
     * <p>已经在 prepare 阶段失败的调用，这里<b>原样返回它的错误</b>，绝不碰 handler。
     * 这条规则让「参数没通过校验」和「工具执行失败」在代码里彻底分开，
     * 也保证了一个坏参数不可能因为写法疏忽而误触发一次真实操作。
     *
     * @param prepared {@link #prepare} 的产物
     * @param context  程序提供的受控环境；工具不自己去猜身份和场景
     * @return 永远非 null。handler 抛异常会被包成 {@code tool_execution_error}
     */
    public ToolExecutionResult invoke(PreparedToolCall prepared, ToolContext context) {
        if (prepared == null) {
            throw new IllegalArgumentException("prepared 不能为 null");
        }
        if (context == null) {
            // context 为 null 是调用方的编程错误，不是模型的错误，所以这里该抛。
            throw new IllegalArgumentException("context 不能为 null");
        }

        // 短路：坏参数不进 handler。
        if (prepared.isFailed()) {
            return prepared.getError();
        }

        ToolDefinition definition = prepared.getDefinition();
        try {
            ToolExecutionResult result =
                    definition.getHandler().execute(prepared.getArguments(), context);
            if (result == null) {
                // handler 是别人写的代码，它违约了也不能让整个循环崩掉。
                return ToolExecutionResult.error("tool_contract_violation",
                        "工具 " + definition.getName() + " 返回了 null");
            }
            return result;
        } catch (RuntimeException e) {
            // 兜底。工具里一个 NPE 不应该终止整个 agent 循环——
            // 它应该变成一条模型能读懂的失败消息，让模型有机会换个参数重试。
            return ToolExecutionResult.error("tool_execution_error",
                    "工具 " + definition.getName() + " 执行异常：" + e.getClass().getSimpleName()
                            + ": " + e.getMessage());
        }
    }
}
