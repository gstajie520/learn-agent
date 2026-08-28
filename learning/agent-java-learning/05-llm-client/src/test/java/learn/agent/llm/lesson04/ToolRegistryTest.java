package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.lesson03.DeviceType;
import learn.agent.llm.lesson03.SceneSnapshot;
import learn.agent.llm.lesson03.ValidationResult;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link ToolRegistry} 的单元测试：验证「准备」和「执行」两步分离。
 *
 * <p>覆盖的核心规则：</p>
 * <ul>
 *   <li>注册时校验工具名、描述、handler，重复注册被拒绝；</li>
 *   <li>{@code prepare} 零副作用，四种失败全部变成 error 态返回值，不抛异常；</li>
 *   <li>{@code invoke} 是全类唯一有副作用的地方，坏参数不进 handler；</li>
 *   <li>handler 抛异常被兜住，变成 {@code tool_execution_error} 而不是让循环崩掉。</li>
 * </ul>
 */
public class ToolRegistryTest {

    /** 一个只读工具，handler 记录自己是否被调用。 */
    private static final class RecordingHandler implements ToolHandler {
        int callCount = 0;

        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            callCount++;
            return ToolExecutionResult.success("ok");
        }
    }

    private ToolRegistry registryWithListTool() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ,
                new RecordingHandler()));
        return registry;
    }

    private ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        return new ToolContext("test-user", new SceneSnapshot(20, 20, 5, devices));
    }

    /**
     * 规则：注册时校验工具名，非法名字在启动期就拒绝。
     *
     * <p><b>为什么重要：</b>工具名会被拼进发给模型的 JSON，也会被模型原样回传。
     * 允许空格或中文，出问题时你分不清是模型抄错了还是自己写错了。
     * 启动期就崩，比模型调用时才崩好排查得多。</p>
     *
     * <p><b>违反会怎样：</b>名字带空格或特殊字符，模型回传时可能被协议层
     * 转义或截断，导致「注册了却永远匹配不上」的诡异 bug。</p>
     */
    @Test
    public void shouldRejectInvalidToolNameAtRegistration() {
        ToolRegistry registry = new ToolRegistry();
        assertThrows(IllegalArgumentException.class, () ->
                registry.register(new ToolDefinition(
                        "delete device", "带空格的名字", "{}", ToolEffect.READ,
                        new RecordingHandler())));
    }

    /**
     * 规则：重复注册同名工具被拒绝，而不是静默覆盖。
     *
     * <p><b>为什么重要：</b>静默覆盖是最难查的 bug：两处注册同名工具，
     * 行为取决于类加载顺序，测试环境和生产环境可能不一样。</p>
     */
    @Test
    public void shouldRejectDuplicateRegistration() {
        ToolRegistry registry = registryWithListTool();
        assertThrows(IllegalArgumentException.class, () ->
                registry.register(new ToolDefinition(
                        "list_devices", "重复", "{}", ToolEffect.READ,
                        new RecordingHandler())));
    }

    /**
     * 规则：{@code prepare} 对不存在的工具名返回 {@code tool_not_found}，不抛异常。
     *
     * <p><b>为什么重要：</b>模型幻觉出工具名是预期内事件。把它变成一条
     * 能回传给模型的错误，模型下一轮就能改口；抛异常则会让整个循环崩掉。</p>
     */
    @Test
    public void shouldReturnToolNotFoundForUnknownTool() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "delete_everything", "{}"));

        assertTrue(prepared.isFailed());
        assertEquals("tool_not_found", prepared.getError().getErrorCode());
        assertNull(prepared.getDefinition());
    }

    /**
     * 规则：{@code prepare} 对非法 JSON 参数返回 {@code invalid_arguments_json}。
     *
     * <p><b>为什么重要：</b>协议里 arguments 是「装着 JSON 的字符串」，
     * 模型输出不合法 JSON 是常态。解析失败必须变成返回值，而不是异常。</p>
     */
    @Test
    public void shouldReturnInvalidJsonForMalformedArguments() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "list_devices", "这不是JSON"));

        assertTrue(prepared.isFailed());
        assertEquals("invalid_arguments_json", prepared.getError().getErrorCode());
    }

    /**
     * 规则：{@code prepare} 对非对象参数返回 {@code arguments_not_object}。
     *
     * <p><b>为什么重要：</b>合法 JSON 不一定是对象。数组 {@code [1,2]} 或
     * 字符串 {@code "abc"} 都能解析，但按字段取值会失败。必须显式区分。</p>
     */
    @Test
    public void shouldReturnNotObjectForArrayArguments() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "list_devices", "[1,2,3]"));

        assertTrue(prepared.isFailed());
        assertEquals("arguments_not_object", prepared.getError().getErrorCode());
    }

    /**
     * 规则：{@code prepare} 成功时返回 ready 态，参数已解析成 JsonNode。
     *
     * <p><b>为什么重要：</b>这是「检查」和「执行」分离的成果 ——
     * 执行阶段拿到的参数已经是解析好、校验过的，不需要再检查一遍。</p>
     */
    @Test
    public void shouldReturnReadyForValidArguments() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "list_devices", "{}"));

        assertFalse(prepared.isFailed());
        assertNotNull(prepared.getDefinition());
        assertNotNull(prepared.getArguments());
        assertTrue(prepared.getArguments().isObject());
    }

    /**
     * 规则：{@code prepare} 零副作用 —— 不调用 handler。
     *
     * <p><b>为什么重要：</b>「这次调用合不合法」和「这次调用要不要执行」
     * 是两个决定。prepare 只回答前者，绝不能顺手把工具跑了。
     * 否则破坏性工具会在「还没确认」时就被执行。</p>
     */
    @Test
    public void shouldNotInvokeHandlerDuringPrepare() {
        RecordingHandler handler = new RecordingHandler();
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, handler));

        registry.prepare(new ToolCall("call-1", "list_devices", "{}"));

        assertEquals(0, handler.callCount, "prepare 阶段绝不能执行 handler");
    }

    /**
     * 规则：{@code invoke} 对已失败的 prepared 调用原样返回错误，不碰 handler。
     *
     * <p><b>为什么重要：</b>这条规则保证「参数没通过校验」和「工具执行失败」
     * 在代码里彻底分开，也保证一个坏参数不可能因为写法疏忽而误触发真实操作。</p>
     */
    @Test
    public void shouldShortCircuitFailedPreparedCall() {
        RecordingHandler handler = new RecordingHandler();
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, handler));

        PreparedToolCall failed = registry.prepare(
                new ToolCall("call-1", "list_devices", "不是JSON"));
        ToolExecutionResult result = registry.invoke(failed, context());

        assertTrue(result.isError());
        assertEquals("invalid_arguments_json", result.getErrorCode());
        assertEquals(0, handler.callCount, "失败的调用绝不能执行 handler");
    }

    /**
     * 规则：{@code invoke} 对 ready 调用执行 handler 并返回其结果。
     *
     * <p><b>为什么重要：</b>这是全类唯一有副作用的地方，也是「执行」的唯一切入点。
     * 所有真实操作都必须经过这里，才能被统一审计和兜底。</p>
     */
    @Test
    public void shouldInvokeHandlerForReadyCall() {
        RecordingHandler handler = new RecordingHandler();
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, handler));

        PreparedToolCall ready = registry.prepare(
                new ToolCall("call-1", "list_devices", "{}"));
        ToolExecutionResult result = registry.invoke(ready, context());

        assertFalse(result.isError());
        assertEquals(1, handler.callCount);
    }

    /**
     * 规则：handler 抛异常被兜住，变成 {@code tool_execution_error}。
     *
     * <p><b>为什么重要：</b>工具是别人写的代码，它违约了（抛 NPE）也不能让
     * 整个 agent 循环崩掉。兜住之后变成一条模型能读懂的失败消息，
     * 模型有机会换个参数重试。</p>
     */
    @Test
    public void shouldWrapHandlerException() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "boom", "会炸的工具", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        throw new NullPointerException("故意的");
                    }
                }));

        PreparedToolCall ready = registry.prepare(new ToolCall("call-1", "boom", "{}"));
        ToolExecutionResult result = registry.invoke(ready, context());

        assertTrue(result.isError());
        assertEquals("tool_execution_error", result.getErrorCode());
    }

    /**
     * 规则：handler 返回 null 被识别为契约违约。
     *
     * <p><b>为什么重要：</b>null 结果会让上层误以为工具没执行。显式识别并
     * 转成错误，比让 null 一路传播到回传逻辑里再炸要好排查。</p>
     */
    @Test
    public void shouldTreatNullHandlerResultAsContractViolation() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "null_tool", "返回 null 的工具", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return null;
                    }
                }));

        PreparedToolCall ready = registry.prepare(new ToolCall("call-1", "null_tool", "{}"));
        ToolExecutionResult result = registry.invoke(ready, context());

        assertTrue(result.isError());
        assertEquals("tool_contract_violation", result.getErrorCode());
    }

    /**
     * 规则：带业务校验器的工具，校验失败返回 {@code invalid_arguments}。
     *
     * <p><b>为什么重要：</b>JSON Schema 只能保证类型，保证不了业务约束。
     * 校验器在 prepare 阶段拦截，失败同样变成返回值而不是异常。</p>
     */
    @Test
    public void shouldRunValidatorAndReturnInvalidArguments() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "create_device", "新增设备", "{}", ToolEffect.WRITE,
                new RecordingHandler(),
                new ToolArgumentValidator() {
                    @Override
                    public ValidationResult<JsonNode> validate(JsonNode arguments) {
                        if (!arguments.has("deviceType")) {
                            return ValidationResult.fail("缺少 deviceType");
                        }
                        return ValidationResult.ok(arguments);
                    }
                }));

        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "create_device", "{\"x\":1}"));

        assertTrue(prepared.isFailed());
        assertEquals("invalid_arguments", prepared.getError().getErrorCode());
    }
}