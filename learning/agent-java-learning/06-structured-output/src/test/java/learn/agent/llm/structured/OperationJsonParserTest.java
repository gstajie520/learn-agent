package learn.agent.llm.structured;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 解析层测试：把模型输出变成领域对象。
 *
 * <p>测试目标：证明解析层能扛住模型输出的<b>各种不规范形态</b>。
 * 这一层的存在理由很实际 —— 你在提示词里写了一百遍「只输出 JSON」，
 * 模型还是会加代码围栏、加客套话，或者干脆用自然语言回答。</p>
 *
 * <p>核心立场：<b>模型输出是不可信输入</b>，和 HTTP 请求体一个性质。
 * 不能因为提示词里要求了某种格式，就假设它一定是那个格式。</p>
 *
 * <p>另一条贯穿本类的原则是<b>宽容的边界</b>：
 * 提取 JSON、大小写不敏感属于「适配模型习惯」，可以宽容；
 * 字符串转数字、猜字段名属于「替模型掩盖错误」，绝不宽容。</p>
 */
public class OperationJsonParserTest {

    private final OperationJsonParser parser = new OperationJsonParser();

    /** 标准纯 JSON 正常解析且字段逐一落位：这是基准线，没有它后面那些失败测试也可能只是因为解析器拒绝一切输入。 */
    @Test
    public void shouldParseCleanJson() {
        // Arrange：模型完全按要求输出。
        String raw = "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":30,\"y\":40,"
                + "\"reason\":\"用户要求在北侧加雷达\"}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：解析成功，六个字段都正确。
        assertTrue(result.isValid(), "解析应当成功，实际错误：" + result.getErrors());
        SceneOperation operation = result.getValue();
        assertEquals(OperationType.CREATE, operation.getType());
        assertEquals(DeviceType.RADAR, operation.getDeviceType());
        assertEquals(Integer.valueOf(30), operation.getX());
        assertEquals(Integer.valueOf(40), operation.getY());
        assertEquals("用户要求在北侧加雷达", operation.getReason());
    }

    /** Markdown 代码围栏必须被剥离：提示词写「不要用围栏」能降低概率但降不到零，
     * 不处理就得到一个同样输入有时成功有时失败的偶发故障，无法稳定复现所以极难定位。 */
    @Test
    public void shouldStripMarkdownCodeFence() {
        // Arrange：模型习惯性加上了围栏，还带了前后客套话。
        String raw = "好的，这是操作：\n```json\n{\"operation\":\"delete\",\"targetId\":\"cam-01\"}\n```\n希望有帮助！";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：围栏和客套话都被忽略，内容正常解析。
        assertTrue(result.isValid(), "应当剥离围栏，实际错误：" + result.getErrors());
        assertEquals(OperationType.DELETE, result.getValue().getType());
        assertEquals("cam-01", result.getValue().getTargetId());
    }

    /** JSON 前后的客套话要被忽略：措辞千变万化，靠匹配「好的」「这是」这类前缀是治不完的，
     * 定位第一个花括号再按深度配对才稳定。 */
    @Test
    public void shouldIgnoreSurroundingProse() {
        // Arrange：JSON 夹在两段说明文字中间。
        String raw = "根据你的描述，我生成了以下操作：\n"
                + "{\"operation\":\"move\",\"targetId\":\"cam-01\",\"x\":60,\"y\":60}\n"
                + "如需调整请告诉我。";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：只取出中间的 JSON。
        assertTrue(result.isValid());
        assertEquals(OperationType.MOVE, result.getValue().getType());
        assertEquals(Integer.valueOf(60), result.getValue().getX());
    }

    /** 字符串字面量里的花括号不能干扰配对：{@code reason} 引用用户原话时就会带上花括号，
     * 在那里提前截断会报「JSON 格式不合法」，让人去查模型，而 bug 在我们自己的提取算法里。 */
    @Test
    public void shouldHandleBracesInsideStringValues() {
        // Arrange：reason 字段里含有花括号。
        String raw = "{\"operation\":\"delete\",\"targetId\":\"cam-01\","
                + "\"reason\":\"用户说 {删掉它} 所以执行删除\"}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：完整解析，没有被字符串里的括号带偏。
        assertTrue(result.isValid(), "字符串内的括号不应影响配对，实际错误：" + result.getErrors());
        assertTrue(result.getValue().getReason().contains("{删掉它}"));
    }

    /** 纯文本要返回可读错误而不是抛异常：模型有时直接反问一句，抛未捕获异常会让接口返回 500，
     * 用户看到「系统错误」，其实只需要换个说法重新描述。 */
    @Test
    public void shouldReportErrorForPlainText() {
        // Arrange：模型反问了一句，完全没有 JSON。
        String raw = "请问你想在场景的哪个位置添加设备呢？";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：失败但不抛异常，且错误里带上原文片段便于排查。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("JSON"));
    }

    /** 截断的 JSON 返回错误而不是抛异常：输出撞上 {@code maxOutputTokens} 时恰好产生这种「开头合法、结尾缺失」的形态，
     * 这里和第 1 课的 {@code finishReason=LENGTH} 是同一类故障的两道防线，上游漏检时这里兜住。 */
    @Test
    public void shouldReportErrorForTruncatedJson() {
        // Arrange：JSON 写到一半断了。
        String raw = "{\"operation\":\"create\",\"deviceType\":\"rad";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：可读错误，不是堆栈。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("截断")
                        || result.getErrorMessage().contains("找不到"),
                "错误应提示截断或找不到完整对象，实际：" + result.getErrorMessage());
    }

    /** {@code "x": "30"} 这类字符串坐标必须拒绝而不是自动转换：一旦容忍字符串数字，
     * {@code "三十"} 也会被转成 0，类型混乱向下游扩散后故障点离原因很远。 */
    @Test
    public void shouldRejectStringCoordinates() {
        // Arrange：坐标被写成字符串。
        String raw = "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":\"30\",\"y\":40}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：识别为类型问题，错误信息明确指出「必须是数字」。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("必须是数字"));
    }

    /** 小数坐标被拒绝：坐标是整数格，模型算出的 10.5 静默取整会让设备落在用户没预期的位置。 */
    @Test
    public void shouldRejectFractionalCoordinates() {
        // Arrange
        String raw = "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":10.5,\"y\":40}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("整数"));
    }

    /** 未知的 operation 值要报错并列出全部合法取值：你定义 create，模型会自己造出 add，
     * 这类幻觉枚举结构上是个合法字符串，而错误里带上合法值它下一轮才不用再猜。 */
    @Test
    public void shouldReportUnknownOperationWithValidValues() {
        // Arrange：add 不在枚举里（我们用的是 create）。
        String raw = "{\"operation\":\"add\",\"deviceType\":\"radar\",\"x\":1,\"y\":1}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：报错并列出合法取值。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("create"),
                "错误信息应列出合法取值，实际：" + result.getErrorMessage());
    }

    /** 未知的 deviceType 同样报错并列出合法值：模型会输出「热成像雷达」「sensor」这些看起来合理的类型，
     * 这正是这里用枚举而不是 String 的原因。 */
    @Test
    public void shouldReportUnknownDeviceType() {
        // Arrange：sensor 不在枚举里。
        String raw = "{\"operation\":\"create\",\"deviceType\":\"sensor\",\"x\":1,\"y\":1}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("radar"));
    }

    /** 大小写不同的枚举值应当被接受：{@code "CREATE"} 和 {@code "Radar"} 不改变语义，
     * 强行拒绝只是白花一轮 token 和延迟，宽容度要用在不影响语义的地方。 */
    @Test
    public void shouldAcceptDifferentCasing() {
        // Arrange：全大写输出。
        String raw = "{\"operation\":\"CREATE\",\"deviceType\":\"RADAR\",\"x\":5,\"y\":5}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：正常解析，不因大小写失败。
        assertTrue(result.isValid(), "大小写差异不应导致失败，实际错误：" + result.getErrors());
        assertEquals(OperationType.CREATE, result.getValue().getType());
        assertEquals(DeviceType.RADAR, result.getValue().getDeviceType());
    }

    /** 契约外的多余字段要报错而不是静默忽略：{@code "rotation": 90} 说明模型认为能设朝向而系统并不支持，
     * 默默丢掉的话用户会以为是渲染 bug，真正原因却在几层之外，比报错难查得多。 */
    @Test
    public void shouldRejectUnknownFields() {
        // Arrange：模型多输出了一个系统不支持的字段。
        String raw = "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":1,\"y\":1,\"rotation\":90}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：明确报出，让理解偏差尽早暴露。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("rotation"));
    }

    /** 已知缺陷，记录的不是期望行为：数组输入只有第一个元素被处理，其余静默丢弃 ——
     * 用户说「删掉那两台」，系统只执行一个还回「已完成」，报错用户会重试，静默丢弃他根本不知道。 */
    @Test
    public void shouldSilentlyKeepOnlyFirstElementOfArray_knownLimitation() {
        // Arrange：模型想做两个操作，返回了数组。
        String raw = "[{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":1,\"y\":1},"
                + "{\"operation\":\"create\",\"deviceType\":\"camera\",\"x\":2,\"y\":2}]";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：第一个元素被当成唯一操作，解析"成功"了。
        assertTrue(result.isValid(),
                "当前实现会取出第一个对象并解析成功，实际：" + result.getErrorMessage());
        assertEquals(DeviceType.RADAR, result.getValue().getDeviceType());

        // Assert：第二个操作（camera）确实消失了，没有任何提示。
        // 这一行是本测试的重点：它证明了丢弃是静默的。
        assertEquals(1, result.getValue().getX().intValue());
    }

    /** 空输入和 null 要安全处理而不抛 NPE：模型返回空内容是真实会发生的，解析层作为防线自己不能先崩。 */
    @Test
    public void shouldHandleEmptyAndNullInput() {
        // Act + Assert：三种空输入都返回失败而不是抛异常。
        assertFalse(parser.parse(null).isValid());
        assertFalse(parser.parse("").isValid());
        assertFalse(parser.parse("   ").isValid());
    }

    /** 空白 {@code targetId} 归一成 null：空字符串在 JSON 里合法，{@code != null} 会放行，
     * 于是空 id 进下游查询后报的是「设备不存在」，让人以为是数据问题而不是模型输出问题。 */
    @Test
    public void shouldTreatBlankTargetIdAsMissing() {
        // Arrange：targetId 是空白。
        String raw = "{\"operation\":\"delete\",\"targetId\":\"   \"}";

        // Act
        ValidationResult<SceneOperation> result = parser.parse(raw);

        // Assert：解析本身成功（类型没错），但 targetId 归一成 null，
        // 交由 Schema 层报「必填项缺失」—— 各层职责清晰。
        assertTrue(result.isValid());
        assertNull(result.getValue().getTargetId());
    }
}
