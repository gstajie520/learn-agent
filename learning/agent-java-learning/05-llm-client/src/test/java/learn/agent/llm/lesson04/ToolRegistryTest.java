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

    /** 工具名非法（这里带空格）在注册期就抛异常，而不是等模型调用时才发现。 */
    @Test
    public void shouldRejectInvalidToolNameAtRegistration() {
        ToolRegistry registry = new ToolRegistry();
        assertThrows(IllegalArgumentException.class, () ->
                registry.register(new ToolDefinition(
                        "delete device", "带空格的名字", "{}", ToolEffect.READ,
                        new RecordingHandler())));
    }

    /** 同名工具重复注册被拒绝：静默覆盖会让行为取决于类加载顺序。 */
    @Test
    public void shouldRejectDuplicateRegistration() {
        ToolRegistry registry = registryWithListTool();
        assertThrows(IllegalArgumentException.class, () ->
                registry.register(new ToolDefinition(
                        "list_devices", "重复", "{}", ToolEffect.READ,
                        new RecordingHandler())));
    }

    /** 未注册的工具名返回 {@code tool_not_found} 而不抛异常：模型幻觉是预期内事件，要能回传给它改口。 */
    @Test
    public void shouldReturnToolNotFoundForUnknownTool() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "delete_everything", "{}"));

        assertTrue(prepared.isFailed());
        assertEquals("tool_not_found", prepared.getError().getErrorCode());
        assertNull(prepared.getDefinition());
    }

    /** arguments 不是合法 JSON 时返回 {@code invalid_arguments_json}。 */
    @Test
    public void shouldReturnInvalidJsonForMalformedArguments() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "list_devices", "这不是JSON"));

        assertTrue(prepared.isFailed());
        assertEquals("invalid_arguments_json", prepared.getError().getErrorCode());
    }

    /** 合法 JSON 但不是对象（这里是数组）单独报 {@code arguments_not_object}。 */
    @Test
    public void shouldReturnNotObjectForArrayArguments() {
        ToolRegistry registry = registryWithListTool();
        PreparedToolCall prepared = registry.prepare(
                new ToolCall("call-1", "list_devices", "[1,2,3]"));

        assertTrue(prepared.isFailed());
        assertEquals("arguments_not_object", prepared.getError().getErrorCode());
    }

    /** prepare 成功后参数已是解析好的 JsonNode，执行阶段不必再解析校验一遍。 */
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

    /** prepare 零副作用：它只回答「这次调用合不合法」，不能顺手把工具跑了。 */
    @Test
    public void shouldNotInvokeHandlerDuringPrepare() {
        RecordingHandler handler = new RecordingHandler();
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, handler));

        registry.prepare(new ToolCall("call-1", "list_devices", "{}"));

        assertEquals(0, handler.callCount, "prepare 阶段绝不能执行 handler");
    }

    /** 已失败的 prepared 进 invoke 时原样返回错误，坏参数不可能误触发真实操作。 */
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

    /** invoke 是全类唯一执行 handler 的地方，真实操作都从这里过。 */
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

    /** handler 抛异常被兜成 {@code tool_execution_error}：别人写的工具违约不该让整个循环崩掉。 */
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

    /** handler 返回 null 被识别成 {@code tool_contract_violation}，而不是让 null 往下传播。 */
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

    /** 业务校验器在 prepare 阶段拦截，失败报 {@code invalid_arguments}：Schema 管类型，校验器管业务。 */
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