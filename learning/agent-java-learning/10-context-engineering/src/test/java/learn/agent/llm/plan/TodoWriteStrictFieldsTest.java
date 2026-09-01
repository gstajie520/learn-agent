package learn.agent.llm.plan;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import learn.agent.llm.structured.ValidationResult;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code todo_write} 拒绝未知字段（教材两处 Zod {@code .strict()} 的等价物）。
 *
 * <h3>这个测试类为什么存在</h3>
 * <p>原先的校验器只按名字取 {@code content} 和 {@code status}，多出来的字段
 * 既不报错也不保存 —— 被<b>静默丢掉</b>。表面上「多几个字段无所谓」，
 * 实际后果和 {@link TodoTracker} 的核心机制直接冲突。</p>
 *
 * <p>工具结果回传整张 JSON 的<b>全部理由</b>是让模型逐字段对比、自己发现
 * 「我写进去的」和「系统接受的」有没有出入。静默丢字段恰好制造出一次
 * <b>模型看得见、但没有任何解释的差异</b> —— 它只能猜是不是有人动过它的计划。
 * 拒绝未知字段是把这种情况变成一条明确的、可改的错误。</p>
 *
 * <p>对应教材 {@code ch05/tests/todos.test.ts:110-111}，Python 侧
 * {@code ch05_agent/tests/test_todos.py:60-61} 也钉了同样两条。</p>
 */
public class TodoWriteStrictFieldsTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final TodoWriteValidator validator = new TodoWriteValidator();

    /**
     * 规则：单项里出现未知字段 → 非法。
     *
     * <p>违反会怎样：{@code priority} 被悄悄丢掉，回传快照里没有它，
     * 模型对比时发现差异却收不到任何原因说明。</p>
     */
    @Test
    @DisplayName("单项出现未知字段：拒绝，并在错误信息里点出字段名")
    void shouldRejectUnknownFieldInsideItem() throws Exception {
        ValidationResult<JsonNode> result = validate(
                "{\"todos\":[{\"content\":\"x\",\"status\":\"pending\",\"priority\":\"high\"}]}");

        assertFalse(result.isValid(), "带未知字段的单项必须被拒绝");
        // 错误信息要能让模型下一轮改对，所以必须点出是哪个字段。
        assertTrue(result.getErrorMessage().contains("priority"),
                "错误信息应当点出未知字段名，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：顶层出现未知字段 → 非法。
     *
     * <p>不拒的话模型可以持续发明包装字段（{@code {"todos":[...],"reason":"..."}}）
     * 而永远不被纠正 —— 它会以为这些字段被系统接受了。</p>
     */
    @Test
    @DisplayName("顶层出现未知字段：拒绝")
    void shouldRejectUnknownFieldAtTopLevel() throws Exception {
        ValidationResult<JsonNode> result = validate(
                "{\"todos\":[{\"content\":\"x\",\"status\":\"pending\"}],\"extra\":true}");

        assertFalse(result.isValid(), "顶层带未知字段必须被拒绝");
        assertTrue(result.getErrorMessage().contains("extra"),
                "错误信息应当点出未知字段名，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：合法的两字段快照仍然通过。
     *
     * <p>和上面两条成对。少了这条，「把所有写入都拒掉」也能让前两条变绿，
     * 那样这道锁就从校验退化成了功能残废。</p>
     */
    @Test
    @DisplayName("只有 content 和 status 的快照正常通过")
    void shouldAcceptExactlyKnownFields() throws Exception {
        ValidationResult<JsonNode> result = validate(
                "{\"todos\":[{\"content\":\"建 schema\",\"status\":\"completed\"},"
                        + "{\"content\":\"补测试\",\"status\":\"pending\"}]}");

        assertTrue(result.isValid(),
                "合法快照不该被这道锁挡住，实际错误：" + result.getErrorMessage());
    }

    /**
     * 规则：未知字段错误和其它错误<b>一次报全</b>。
     *
     * <p>这条守的是校验器的既有风格（第 3 课确立）：模型一次写错三处，
     * 就一次把三处都告诉它。分三轮报会烧掉三轮 token，而且模型每轮只改一处
     * 的时候，很容易把上一轮改对的地方又改坏。</p>
     */
    @Test
    @DisplayName("未知字段与非法状态一次性全部报出")
    void shouldReportUnknownFieldTogetherWithOtherErrors() throws Exception {
        ValidationResult<JsonNode> result = validate(
                "{\"todos\":[{\"content\":\"x\",\"status\":\"blocked\",\"priority\":\"high\"}]}");

        assertFalse(result.isValid());
        String message = result.getErrorMessage();
        // 两类问题都要出现：非法状态值，以及未知字段。
        assertTrue(message.contains("blocked"),
                "应当报出非法状态，实际：" + message);
        assertTrue(message.contains("priority"),
                "应当同时报出未知字段，实际：" + message);
    }

    /**
     * 规则：缺 {@code todos} 时，已经收集到的未知字段错误也要一起报。
     *
     * <p>「缺 todos」和「多了个 todo」常常是同一个笔误的两面
     * （{@code {"todo":[...]}}）。只报「缺 todos」会让模型以为自己漏写了字段，
     * 于是在保留错字段的基础上再加一个 —— 下一轮仍然失败。</p>
     */
    @Test
    @DisplayName("缺 todos 且有未知字段：两条错误一起报，不只报一半")
    void shouldReportBothMissingTodosAndUnknownField() throws Exception {
        ValidationResult<JsonNode> result = validate(
                "{\"todo\":[{\"content\":\"x\",\"status\":\"pending\"}]}");

        assertFalse(result.isValid());
        String message = result.getErrorMessage();
        assertTrue(message.contains("todos"),
                "应当报出缺少 todos，实际：" + message);
        assertTrue(message.contains("todo"),
                "应当同时报出那个拼错的字段名，实际：" + message);
    }

    private ValidationResult<JsonNode> validate(String json) throws Exception {
        return validator.validate(MAPPER.readTree(json));
    }
}
