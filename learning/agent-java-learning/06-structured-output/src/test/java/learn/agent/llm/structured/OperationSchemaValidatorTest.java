package learn.agent.llm.structured;

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

    /** 完整合法的 CREATE 能通过第一层：正常路径不先跑通，后面那些拒绝测试可能只是因为校验器把一切都拒了。 */
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
     * CREATE 缺 deviceType 必须拒绝：deviceType 字段本身允许为 null（DELETE 不需要它），
     * 类型系统管不了这种搭配约束，放过去下游要么 NPE，要么猜一个默认类型往场景里放错设备。
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

    /** CREATE 缺坐标必须拒绝：补个默认的 (0,0) 会让设备全堆在角落，用户以为系统坏了，宁可要求模型补全。 */
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

    /** MOVE 缺 targetId 必须拒绝：必填项随操作类型而变（CREATE 要 deviceType，MOVE 要 targetId），这种按类型分支的约束正是 Schema 层的职责。 */
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

    /** DELETE 缺 targetId 必须拒绝：删除不可逆，目标不明确时不能留任何「猜一个」的余地。 */
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
     * 负坐标必须拒绝：这一层比的是写死的常量而不是场景实际宽高，因为「不能为负」任何场景下都成立，
     * 而「坐标 5000 是否越界」得先知道场景多大，那是第二层的事。
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

    /** 荒谬的大坐标必须拒绝：999999 不用查场景也知道不合理，在这里挡掉就不用把明显错误的数据带进需要查询状态的下一层。 */
    @Test
    public void shouldRejectAbsurdlyLargeCoordinates() {
        // Arrange：远超任何合理场景尺寸。
        SceneOperation operation = SceneOperation.create(DeviceType.CAMERA, 999999, 40, "巨大坐标");

        // Act
        ValidationResult<SceneOperation> result = validator.validate(operation);

        // Assert
        assertFalse(result.isValid());
    }

    /** CLEAR_ALL 不缺任何必填字段，第一层必须放行：它危险不危险由第二层和确认环节判断，Schema 层越权替别人做决定，分层就没意义了。 */
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

    /** 缺 reason 必须拒绝：预览只显示「将删除 device-3」而不说为什么，用户无法判断模型有没有理解错，只能盲目点确认，这道防线就形同虚设。 */
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

    /** 多个结构问题一次全部报出：只报第一个的话，N 个错误要 N 轮真实模型调用才修完，延迟和成本都变成 N 倍。 */
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
     * null 输入返回失败结果而不是抛 NPE：这一层直面模型输出，null 属于可能发生的脏输入（第二层的 null 是调用方 bug，所以那边抛 {@link IllegalArgumentException}），
     * 抛 NPE 会把一次脏输出变成 500 而不是一条能回传给模型的提示。
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
