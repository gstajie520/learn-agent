package learn.agent.llm.lesson03;

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

    /**
     * 规则：标准的纯 JSON 正常解析，字段逐一落位。
     *
     * <p><b>为什么重要：</b>基准线。先确认模型配合良好时能走通，
     * 后面的失败测试才有意义 —— 否则可能是解析器拒绝一切输入。</p>
     */
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

    /**
     * 规则：★ Markdown 代码围栏必须被剥离。
     *
     * <p><b>为什么重要：</b>这是模型<b>最常见</b>的不规范输出。
     * 模型被训练成用 ```json 包裹代码，因为那在聊天界面里显示更友好。
     * 提示词写「不要用代码围栏」能降低概率，但降不到零。</p>
     *
     * <p><b>违反会怎样：</b>{@code ObjectMapper} 遇到反引号直接抛
     * {@code JsonParseException}。不处理的话你会看到一个「偶发」的解析失败 ——
     * 同样的输入有时成功有时失败，因为模型是否加围栏本身就不稳定。
     * 这种间歇性故障极难定位，因为你无法稳定复现。</p>
     */
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

    /**
     * 规则：JSON 前后的解释性文字要被忽略。
     *
     * <p><b>为什么重要：</b>模型爱加礼貌用语。这属于对话习惯，不是错误。</p>
     *
     * <p><b>为什么用括号配对而不是字符串匹配：</b>客套话的措辞千变万化，
     * 靠匹配「好的」「这是」之类的前缀是治不完的。
     * 定位第一个 <code>{</code> 再按括号深度配对，才是稳定做法。</p>
     */
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

    /**
     * 规则：字符串字面量内部的花括号不能干扰括号配对。
     *
     * <p><b>为什么重要：</b>这是括号配对算法的经典边界。模型给的 {@code reason}
     * 里完全可能包含花括号（比如引用了用户原话）。</p>
     *
     * <p><b>违反会怎样：</b>在字符串内部的 <code>}</code> 处提前截断，
     * 得到一段残缺 JSON，解析失败。而报错会说「JSON 格式不合法」，
     * 让人以为是模型的问题 —— 实际是我们自己的提取算法有 bug。</p>
     */
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

    /**
     * 规则：完全不含 JSON 的纯文本要返回可读错误，而不是抛异常。
     *
     * <p><b>为什么重要：</b>模型有时干脆不按格式来，直接用自然语言回答或反问。
     * 这时不该崩，而该返回一个能回传给模型的提示。</p>
     *
     * <p><b>违反会怎样：</b>抛出未捕获异常，接口返回 500。
     * 用户看到「系统错误」，而实际上只是需要换个说法重新描述。</p>
     */
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

    /**
     * 规则：被截断的 JSON（括号未闭合）返回错误而不是抛异常。
     *
     * <p><b>为什么重要：</b>输出撞上 {@code maxOutputTokens} 时，恰好会产生
     * 这种「开头合法、结尾缺失」的 JSON。这和第 1 课的
     * {@code finishReason=LENGTH} 呼应 —— 两处都在防同一类故障，
     * 属于纵深防御：即使上游漏了检查，这里也能兜住。</p>
     */
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

    /**
     * 规则：★ 坐标是字符串时必须拒绝，不做自动转换。
     *
     * <p><b>为什么重要：</b>模型经常输出 {@code "x": "30"} 而不是 {@code "x": 30}。
     * 自动转换看起来贴心，但这是个滑坡：一旦开始容忍字符串数字，
     * {@code "三十"} 或 {@code "abc"} 也会被转成 0 或抛出更深层的异常。</p>
     *
     * <p><b>违反会怎样：</b>类型混乱向下游扩散。有的地方能用有的不能，
     * 而故障点离真正的原因很远。明确拒绝并把问题回传给模型，
     * 它下一轮就会输出数字。</p>
     *
     * <p>注意这和「大小写不敏感」并不矛盾：大小写不改变语义，
     * 字符串和数字是真正的类型差异。</p>
     */
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

    /**
     * 规则：小数坐标被拒绝。
     *
     * <p><b>为什么重要：</b>本课约定坐标是整数格。模型可能算出 10.5 这样的值。
     * 静默取整会让设备落在用户没预期的位置。</p>
     */
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

    /**
     * 规则：未知的 operation 值要报错，并列出全部合法取值。
     *
     * <p><b>为什么重要：</b>模型会创造词汇 —— 你定义了 create/move/delete，
     * 它可能输出 add、remove、update。这类幻觉枚举值在
     * 结构上完全合法（是个字符串），只有对照枚举表才能发现。</p>
     *
     * <p><b>为什么错误里要列出合法值：</b>这段文字可以直接回传给模型，
     * 它下一轮就知道该用哪个词。只说「不支持」它还得再猜一次。</p>
     */
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

    /**
     * 规则：未知的 deviceType 同样报错并列出合法值。
     *
     * <p><b>为什么重要：</b>设备类型的幻觉比操作类型更常见 ——
     * 模型会输出「热成像雷达」「sensor」「light」这些看起来合理的值。
     * 这正是用枚举而不是 String 的原因。</p>
     */
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

    /**
     * 规则：大小写不同的枚举值应当被接受。
     *
     * <p><b>为什么重要：</b>模型对大小写不敏感，经常输出 {@code "CREATE"} 或
     * {@code "Radar"}。这属于<b>无害差异</b>，强行拒绝只会增加无谓的重试轮次，
     * 白花 token 和延迟。</p>
     *
     * <p>宽容度要用在不影响语义的地方 —— 这是本类的核心判断标准。</p>
     */
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

    /**
     * 规则：★ 契约外的多余字段要报错，不能静默忽略。
     *
     * <p><b>为什么重要：</b>多余字段本身通常无害，但它是一个<b>信号</b>：
     * 说明模型对任务的理解和契约不一致。模型输出 {@code "rotation": 90}，
     * 意味着它认为可以设置朝向，而系统并不支持。</p>
     *
     * <p><b>违反会怎样：</b>静默忽略的话，用户说「放一台朝北的雷达」，
     * 模型老老实实生成了 rotation，系统默默丢掉。用户看到设备朝向不对，
     * 会以为是渲染 bug 或者需求没实现 —— 而真正的原因是
     * 字段在几层之外被无声丢弃了。这种「静默不生效」比报错难查得多。</p>
     */
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

    /**
     * 规则（已知缺陷）：模型返回数组时，只有第一个元素会被处理，其余<b>被静默丢弃</b>。
     *
     * <p><b>这个测试记录的是缺陷，不是期望行为。</b>本课的
     * {@code extractJsonObject} 从第一个 <code>{</code> 开始提取，
     * 所以 <code>[{A},{B}]</code> 会被当成 {A} 成功解析，
     * B 消失得无声无息。</p>
     *
     * <p><b>为什么危险：</b>用户说「删掉北侧那两台摄像头」，模型返回两个删除操作，
     * 系统只执行了一个，还告诉用户「已完成」。这类静默丢弃比直接报错糟糕得多 ——
     * 报错用户会重试，静默丢弃用户根本不知道出了问题。</p>
     *
     * <p><b>生产实现应该怎么做：</b>解析前先判断整段输出是数组还是对象。
     * 是数组就明确拒绝并告知「本接口一次只接受一个操作」，
     * 或者进入批量确认流程（涉及部分成功、事务边界和逐条确认，属于后续阶段）。</p>
     *
     * <p>把缺陷用测试固定下来的好处：以后有人修了这个行为，
     * 这个测试会失败，提醒他同步更新文档和这条说明。</p>
     */
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

    /**
     * 规则：空输入和 null 要安全处理，不抛 NPE。
     *
     * <p><b>为什么重要：</b>模型返回空内容是真实存在的情况
     * （第 1 课的 {@code isUsable()} 也在防这个）。
     * 解析层作为防线，自己不能先崩。</p>
     */
    @Test
    public void shouldHandleEmptyAndNullInput() {
        // Act + Assert：三种空输入都返回失败而不是抛异常。
        assertFalse(parser.parse(null).isValid());
        assertFalse(parser.parse("").isValid());
        assertFalse(parser.parse("   ").isValid());
    }

    /**
     * 规则：{@code targetId} 为空字符串等同于未提供。
     *
     * <p><b>为什么重要：</b>模型返回 {@code "targetId": ""} 是真实存在的情况。
     * 它在 JSON 里是合法字符串，用 {@code != null} 判断会放行。</p>
     *
     * <p><b>违反会怎样：</b>空 id 进入下游查询，查不到设备，
     * 报错却是「设备不存在」，让人以为是数据问题而非模型输出问题。
     * 归一成 null 后，Schema 层能明确报出「缺少 targetId」。</p>
     */
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
