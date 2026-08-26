package learn.agent.llm.lesson03;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 第一层校验（结构/Schema）的测试。
 *
 * <p><b>这一层管什么：</b>字段搭配是否完整、数值是否在写死的常量范围内。
 * 它<b>不看</b>当前场景里有什么 —— 那是第二层
 * {@link SceneBusinessValidator} 的事。</p>
 *
 * <p><b>为什么要分两层：</b>这一层的规则来自<b>协议</b>（CREATE 必须带
 * deviceType、坐标不能是负数），第二层的规则来自<b>当前状态</b>
 * （device-99 是否存在、场景是否已满）。协议规则不需要查数据库，
 * 状态规则必须查。混在一起写，就没法在没有场景数据的情况下测协议规则，
 * 报错也分不清是「模型格式错了」还是「业务不允许」。</p>
 *
 * <p>本类全部测试都不需要 {@link SceneSnapshot}，这正是分层的直接好处。</p>
 */
public class OperationSchemaValidatorTest {

    private final OperationSchemaValidator validator = new OperationSchemaValidator();

    /**
     * 规则：完整合法的 CREATE 操作通过第一层校验。
     *
     * <p><b>为什么重要：</b>先确认正常路径能过，否则后面的拒绝测试
     * 可能只是因为校验器把一切都拒了。</p>
     */
    @Test
    public void shouldAcceptCompleteCreateOperation() {
        // Arrange：新增雷达，带坐标和理由。
        SceneOperation operation = SceneOperation.create(DeviceType.RADAR, 30, 40, "用户要求北侧加雷达");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert：结构合法。注意这不代表业务合法 —— 场景可能已满。
        assertTrue(result.isValid(), "应当通过结构校验，实际错误：" + result.getErrorMessage());
        assertEquals(OperationType.CREATE, result.getValue().getType());
    }

    /**
     * 规则：CREATE 必须带 deviceType，否则拒绝。
     *
     * <p><b>为什么重要：</b>「新增一个设备」但没说是什么设备，是无法执行的指令。
     * 这类字段搭配约束无法用 Java 类型系统表达（deviceType 字段本身允许为 null，
     * 因为 DELETE 操作不需要它），只能靠显式校验。</p>
     *
     * <p><b>违反会怎样：</b>下游拿到一个 deviceType 为 null 的操作，
     * 要么 NPE，要么被迫猜一个默认类型 —— 猜错就是往用户场景里放错设备。</p>
     */
    @Test
    public void shouldRejectCreateWithoutDeviceType() {
        // Arrange：手动构造一个缺 deviceType 的 CREATE。
        // 用全参构造是为了绕过 create() 工厂方法的便利参数，模拟模型漏字段的情况。
        SceneOperation operation = new SceneOperation(
                OperationType.CREATE, null, null, 30, 40, "缺少设备类型");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert：明确指出缺哪个字段，而不是只说「参数错误」。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("deviceType"),
                "错误信息应指出 deviceType，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：CREATE 必须带坐标。
     *
     * <p><b>为什么重要：</b>不知道放在哪里的「新增」无法执行。
     * 模型有时只说「加一台摄像头」而不给坐标。</p>
     *
     * <p><b>违反会怎样：</b>如果给个默认坐标（比如 0,0），
     * 设备会全部堆在角落，用户以为系统坏了。宁可拒绝并要求模型补全。</p>
     */
    @Test
    public void shouldRejectCreateWithoutCoordinates() {
        // Arrange：有类型但没坐标。
        SceneOperation operation = new SceneOperation(
                OperationType.CREATE, DeviceType.CAMERA, null, null, null, "没给坐标");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert：x 和 y 都应被报出 —— 收集全部错误而不是只报第一个。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("x"));
        assertTrue(result.getErrorMessage().contains("y"));
    }

    /**
     * 规则：MOVE 必须带 targetId，否则不知道移动谁。
     *
     * <p><b>为什么重要：</b>MOVE 和 CREATE 的必填字段不同 ——
     * CREATE 需要 deviceType，MOVE 需要 targetId。
     * 这种「按类型不同而必填项不同」的约束是 Schema 层的典型职责。</p>
     */
    @Test
    public void shouldRejectMoveWithoutTargetId() {
        // Arrange：想移动，但没说移动哪一个。
        SceneOperation operation = new SceneOperation(
                OperationType.MOVE, null, null, 10, 20, "没指定目标");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("targetId"),
                "错误应指出缺少 targetId，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：DELETE 必须带 targetId。
     *
     * <p><b>为什么重要：</b>删除是不可逆操作。目标不明确时必须拒绝，
     * 绝不能有任何「猜一个」的余地。</p>
     */
    @Test
    public void shouldRejectDeleteWithoutTargetId() {
        // Arrange
        SceneOperation operation = new SceneOperation(
                OperationType.DELETE, null, null, null, null, "删除但没说删谁");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("targetId"));
    }

    /**
     * 规则：坐标为负数时拒绝。
     *
     * <p><b>为什么重要：</b>这一层用的是<b>写死的常量</b>范围（不能为负），
     * 而不是当前场景的实际宽高。区别在于：这条规则任何场景下都成立，
     * 不需要查询状态就能判断。</p>
     *
     * <p>「坐标 5000 是否越界」则要看场景多大，那是第二层的事。
     * 这两层的分工，是本课要理解的核心之一。</p>
     */
    @Test
    public void shouldRejectNegativeCoordinates() {
        // Arrange：负坐标。
        SceneOperation operation = SceneOperation.create(DeviceType.RADAR, -5, 40, "负坐标");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("x"),
                "错误应指出 x 越界，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：坐标超过绝对上限时拒绝。
     *
     * <p><b>为什么重要：</b>模型偶尔会输出 999999 这样的数字。
     * 即使不知道当前场景多大，这个值也明显荒谬。
     * 在这一层挡掉，可以避免把明显错误的数据带到需要查询状态的下一层。</p>
     */
    @Test
    public void shouldRejectAbsurdlyLargeCoordinates() {
        // Arrange：远超任何合理场景尺寸。
        SceneOperation operation = SceneOperation.create(DeviceType.CAMERA, 999999, 40, "巨大坐标");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
    }

    /**
     * 规则：CLEAR_ALL 不需要 deviceType 和 targetId，本身结构合法。
     *
     * <p><b>为什么重要：</b>这个测试证明 Schema 层<b>不越权</b>。
     * 「清空全部设备」在结构上是完整的指令，没有缺任何必填字段，
     * 所以这一层必须放行。</p>
     *
     * <p>它危险不危险，是第二层和确认环节的判断 ——
     * 见 {@code SceneBusinessValidatorTest} 里对 CLEAR_ALL 的处理。
     * 每一层只做自己该做的判断，是分层校验能讲清楚的前提。</p>
     */
    @Test
    public void shouldAcceptClearAllAsStructurallyValid() {
        // Arrange：清空操作。
        SceneOperation operation = SceneOperation.clearAll("用户要求清空场景");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert：结构合法。危险性由后续环节判断，不在这一层拦。
        assertTrue(result.isValid(), "CLEAR_ALL 结构上是完整的，应当通过第一层");
        assertTrue(result.getValue().isDestructive(), "但它必须被标记为破坏性操作");
    }

    /**
     * 规则：reason 缺失时拒绝。
     *
     * <p><b>为什么重要：</b>reason 是给<b>人</b>看的。预览界面要显示
     * 「为什么系统认为你想做这件事」，用户才能判断模型有没有理解错。
     * 没有 reason 的操作，用户只能看到「将删除 device-3」，
     * 无法判断这是不是自己的意思。</p>
     *
     * <p><b>违反会怎样：</b>预览失去意义，用户只能盲目点确认，
     * 「预览再确认」这道防线就形同虚设。</p>
     */
    @Test
    public void shouldRejectMissingReason() {
        // Arrange：没有说明理由。
        SceneOperation operation = new SceneOperation(
                OperationType.CREATE, DeviceType.RADAR, null, 10, 20, null);

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("reason"),
                "错误应指出缺少 reason，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：多个结构问题一次全部报出，不是只报第一个。
     *
     * <p><b>为什么重要：</b>这条规则是为了让<b>模型</b>能一次改对。
     * 只报第一个错误的话，模型改完再发，又撞上第二个错误 ——
     * 每一轮都是一次真实的模型调用，都要花钱和时间。</p>
     *
     * <p><b>违反会怎样：</b>N 个错误要 N 轮才能修完，
     * 延迟和成本都变成 N 倍。这和 Spring 的 {@code @Valid}
     * 一次返回全部字段错误是同一个道理（阶段 3 学过）。</p>
     */
    @Test
    public void shouldReportAllStructuralProblemsAtOnce() {
        // Arrange：同时缺 deviceType、缺坐标、缺 reason。
        SceneOperation operation = new SceneOperation(
                OperationType.CREATE, null, null, null, null, null);

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert：四个问题都在错误列表里，模型改一次就能全部修好。
        assertFalse(result.isValid());
        assertTrue(result.getErrors().size() >= 4,
                "应报出至少 4 个问题，实际 " + result.getErrors().size() + " 个：" + result.getErrors());
    }

    /**
     * 规则：null 输入返回失败结果，而不是抛 NPE。
     *
     * <p><b>为什么重要：</b>这一层是<b>防线</b>，防线自己不能先崩。
     * 上游解析失败时可能传下来 null，校验器要能安全应对。</p>
     *
     * <p><b>注意这和第二层的策略不同</b>：{@link SceneBusinessValidator}
     * 对 null 是抛 {@link IllegalArgumentException}。区别在于职责 ——
     * 这一层直面模型输出，null 属于「可能发生的脏输入」；
     * 第二层的输入已经过本层校验，此时还是 null 就说明是调用方的 bug，
     * 应当立刻暴露而不是伪装成校验失败。</p>
     *
     * <p><b>违反会怎样：</b>如果这里抛 NPE，一次模型输出异常会变成
     * 500 错误，而不是一条可以回传给模型让它重试的可读提示。</p>
     */
    @Test
    public void shouldReturnFailureForNullOperation() {
        // Act：校验器是防线，防线自己不能先崩。
        ValidationResult<SceneOperation> result = validator.validate(null);

        // Assert：返回失败结果，而不是抛异常。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("没有可校验的操作对象"),
                "错误信息应说明没有可校验的对象，实际：" + result.getErrorMessage());
    }
}
