package learn.agent.llm.lesson03;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 第二层校验（业务校验）的测试。
 *
 * <p><b>这是整课最重要的测试类</b>，因为它证明的是本课的核心论点：
 * <b>结构正确不代表业务合法</b>。</p>
 *
 * <p>注意这里每个测试的输入，<b>都是能通过第一层 Schema 校验的</b>。
 * 字段该填的都填了、类型都对、搭配都合规。但它们在真实场景下依然非法：
 * 设备不存在、坐标越界、场景已满、设备受保护。</p>
 *
 * <p>如果只做 Schema 校验就直接执行，这些操作会全部通过 —— 然后在数据库层
 * 报外键错误，或者更糟：静默产生脏数据。</p>
 *
 * <p>另一个观察点：这一层<b>必须依赖场景快照</b>，而第一层不需要。
 * 这正是两层分开的原因 —— 第一层是纯函数可以随便测，
 * 第二层的结论会随场景状态变化。同一个操作，在空场景里非法（设备不存在），
 * 在有设备的场景里合法。</p>
 */
public class SceneBusinessValidatorTest {

    /**
     * 构造一个测试场景：20x20 边界，最多 5 台设备，已有 3 台。
     *
     * <p>{@code radar-1} 被标记为受保护设备，用于验证危险操作拦截。</p>
     */
    private SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-1", DeviceType.RADAR);
        devices.put("camera-1", DeviceType.CAMERA);
        devices.put("camera-2", DeviceType.CAMERA);

        Set<String> protectedIds = new LinkedHashSet<String>();
        protectedIds.add("radar-1");

        return new SceneSnapshot(20, 20, 5, devices, protectedIds);
    }

    private SceneBusinessValidator validator() {
        return new SceneBusinessValidator(scene());
    }

    /** 合法新增通过校验并返回 {@link OperationPreview}：拿到的是预览不是「已完成」，场景数据一个字节都没改，真正的修改仍然要等用户点确认。 */
    @Test
    public void shouldAcceptValidCreateAndReturnPreview() {
        // Arrange：在空位新增一台摄像头，场景当前 3 台、上限 5 台。
        SceneOperation operation = SceneOperation.create(DeviceType.CAMERA, 10, 12, "周界补盲");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：校验通过。
        assertTrue(result.isValid(), "合法新增不应被拒绝：" + result.getErrorMessage());

        // Assert：产出是预览，包含「执行前后设备数量」，让用户能判断影响范围。
        OperationPreview preview = result.getValue();
        assertEquals(3, preview.getDeviceCountBefore());
        assertEquals(4, preview.getDeviceCountAfter());
        assertFalse(preview.isDestructive(), "新增不是破坏性操作");

        // Assert：场景本身没有被修改 —— 预览阶段绝不能有副作用。
        assertEquals(3, scene().getDeviceCount());
    }

    /** 移动不存在的设备必须被拒绝：模型编出的 {@code device-99} 格式完全正确、Schema 百分百放行，放过去要么外键报错，要么更新 0 行还返回「成功」。 */
    @Test
    public void shouldRejectMoveOfNonExistentDevice() {
        // Arrange：device-99 不存在。这个 JSON 能通过 Schema 校验。
        SceneOperation operation = SceneOperation.move("device-99", 5, 5, "用户要求移动");

        // Assert 前提：确认它确实能通过第一层，否则这个测试就证明不了分层的价值。
        assertTrue(new OperationSchemaValidator().validate(operation).isValid(),
                "本测试的前提是这个操作结构合法，只有业务上非法");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：被业务层拦住。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("device-99"));
        assertTrue(result.getErrorMessage().contains("不存在"));

        // Assert：错误信息给出真实设备列表，供模型下一轮纠正。
        assertTrue(result.getErrorMessage().contains("radar-1"),
                "错误信息应列出真实设备 id 作为纠错线索，实际：" + result.getErrorMessage());
    }

    /** 删除不存在的设备必须被拒绝：删除不可逆，下游若把「目标不存在」当成「条件不匹配所以不加过滤」，就会变成全表删除。 */
    @Test
    public void shouldRejectDeleteOfNonExistentDevice() {
        // Arrange
        SceneOperation operation = SceneOperation.delete("camera-99", "用户要求删除");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("camera-99"));
        assertTrue(result.getErrorMessage().contains("不存在"));
    }

    /** 删除受保护设备必须被拒绝，哪怕设备真实存在：用户说「把不用的都删了」时模型是在猜，
     * 关键设备一旦误删，恢复成本远高于让用户多点一次确认。 */
    @Test
    public void shouldRejectDeleteOfProtectedDevice() {
        // Arrange：radar-1 存在，但被标记为受保护。
        SceneOperation operation = SceneOperation.delete("radar-1", "用户说这台不用了");

        // Assert 前提：结构合法，且设备确实存在 —— 只有业务规则能拦住它。
        assertTrue(new OperationSchemaValidator().validate(operation).isValid());
        assertTrue(scene().hasDevice("radar-1"), "前提：这台设备是真实存在的");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：被拦住，且说明原因和替代路径。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("radar-1"));
        assertTrue(result.getErrorMessage().contains("保护")
                        || result.getErrorMessage().contains("锁定"),
                "错误应说明设备受保护，实际：" + result.getErrorMessage());
    }

    /** 越界坐标必须被拒绝：Schema 层只能查「x 是不是整数」，(50,50) 在 20x20 里越界、在 100x100 里合法，
     * 放过去设备就落到画布外，用户以为没成功又点一次，于是多出几台幽灵设备。 */
    @Test
    public void shouldRejectCoordinatesOutsideSceneBounds() {
        // Arrange：场景是 20x20，(50, 50) 越界。结构上完全合法。
        SceneOperation operation = SceneOperation.create(DeviceType.RADAR, 50, 50, "北侧补盲");

        // Assert 前提：Schema 层放行 —— 它没有场景尺寸信息，判断不了。
        assertTrue(new OperationSchemaValidator().validate(operation).isValid(),
                "Schema 层看不到场景边界，所以必须放行；这正是需要第二层的原因");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：被业务层拦住，并说明实际边界。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("边界")
                        || result.getErrorMessage().contains("超出"),
                "错误应说明越界，实际：" + result.getErrorMessage());
        assertTrue(result.getErrorMessage().contains("20"),
                "错误信息应包含真实边界值，供模型纠正");
    }

    /** 合法范围是 {@code [0, width)}，边界值本身合法：{@code <=} 和 {@code <} 写反一个字符，设备就被放到场景外一格。 */
    @Test
    public void shouldAcceptCoordinatesExactlyOnBoundary() {
        // Act + Assert：左上角合法。
        assertTrue(validator().validate(
                        SceneOperation.create(DeviceType.CAMERA, 0, 0, "左上角"))
                .isValid(), "(0,0) 应当合法");

        // Act + Assert：右下角合法（19 而不是 20）。
        assertTrue(validator().validate(
                        SceneOperation.create(DeviceType.CAMERA, 19, 19, "右下角"))
                .isValid(), "(19,19) 在 20x20 场景里应当合法");

        // Act + Assert：正好越界一格被拒绝。
        assertFalse(validator().validate(
                        SceneOperation.create(DeviceType.CAMERA, 20, 19, "越界一格"))
                .isValid(), "(20,19) 在 20x20 场景里应当越界");
    }

    /** 负坐标必须被拒绝：模型会用 -1 表达「往左一点」，而负数走到数组下标那一步是直接抛异常。 */
    @Test
    public void shouldRejectNegativeCoordinates() {
        // Act
        ValidationResult<OperationPreview> result = validator().validate(
                SceneOperation.create(DeviceType.RADAR, -1, 5, "往左移"));

        // Assert
        assertFalse(result.isValid());
    }

    /** 场景已满时不允许继续新增：容量是运行时状态，模型在多轮对话里每次新增单独看都合法，累积起来把场景撑爆，
     * 而这种问题演示时不出现，上线跑一段才爆。 */
    @Test
    public void shouldRejectCreateWhenSceneIsFull() {
        // Arrange：构造一个已达上限的场景（2 台上限，已有 2 台）。
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-1", DeviceType.RADAR);
        devices.put("camera-1", DeviceType.CAMERA);
        SceneSnapshot full = new SceneSnapshot(20, 20, 2, devices, new LinkedHashSet<String>());
        SceneBusinessValidator fullValidator = new SceneBusinessValidator(full);

        // Act：再加一台。
        ValidationResult<OperationPreview> result = fullValidator.validate(
                SceneOperation.create(DeviceType.CAMERA, 5, 5, "再加一台"));

        // Assert：被拒绝，并说明当前数量和上限。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("上限")
                        || result.getErrorMessage().contains("已满"),
                "错误应说明容量问题，实际：" + result.getErrorMessage());
    }

    /** 移动已存在设备到界内位置通过校验且数量不变：预览里的前后数量是用户判断影响范围的依据，算错会让人以为设备被复制或丢失。 */
    @Test
    public void shouldAcceptValidMoveAndKeepDeviceCount() {
        // Arrange：camera-1 确实存在，目标坐标在界内。
        SceneOperation operation = SceneOperation.move("camera-1", 15, 15, "调整视角");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：通过，且数量不变。
        assertTrue(result.isValid(), result.getErrorMessage());
        assertEquals(3, result.getValue().getDeviceCountBefore());
        assertEquals(3, result.getValue().getDeviceCountAfter());
    }

    /** 删除通过校验但预览要标记 {@code isDestructive()}：危险程度由预览对象给出而不是让前端按操作类型自己猜，
     * 否则加新操作类型时前端那份判断一定会漏。 */
    @Test
    public void shouldMarkDeletePreviewAsDestructive() {
        // Arrange：camera-2 存在且未受保护。
        SceneOperation operation = SceneOperation.delete("camera-2", "重复覆盖");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：通过校验。
        assertTrue(result.isValid(), result.getErrorMessage());

        // Assert：标记为破坏性，且数量减一。
        assertTrue(result.getValue().isDestructive(), "删除必须标记为破坏性操作");
        assertEquals(3, result.getValue().getDeviceCountBefore());
        assertEquals(2, result.getValue().getDeviceCountAfter());
    }

    /** 有受保护设备时 {@code clear_all} 整体拒绝而不是删掉其余的：{@code clear_all} 不带参数所以结构上永远合法，
     * 这里是唯一能拦住它的地方，而部分执行会留下用户完全没预期又找不回来的中间状态。 */
    @Test
    public void shouldRejectClearAllWhenSceneHasProtectedDevices() {
        // Arrange：默认场景里 radar-1 是受保护设备。
        SceneOperation operation = SceneOperation.clearAll("用户说清理一下");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：整体拒绝，并且错误信息要指出是哪台设备挡住的，
        // 用户才知道下一步该怎么做。
        assertFalse(result.isValid(), "含受保护设备的场景不允许整体清空");
        assertTrue(result.getErrorMessage().contains("radar-1"),
                "错误应指出受保护设备，实际：" + result.getErrorMessage());
        assertTrue(result.getErrorMessage().contains("逐台"),
                "错误应给出可行的替代做法，实际：" + result.getErrorMessage());
    }

    /** 无受保护设备时清空通过校验，但预览要标记破坏性并显示清空后为 0：模型把「清理一下」理解成清空整个场景并不离谱，
     * 挡住它是用户确认那一步的职责，校验层只负责把后果说清楚。 */
    @Test
    public void shouldPreviewClearAllAsDestructiveWhenNothingIsProtected() {
        // Arrange：一个不含受保护设备的场景。
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("camera-1", DeviceType.CAMERA);
        devices.put("camera-2", DeviceType.CAMERA);
        SceneSnapshot scene = new SceneSnapshot(
                100, 100, 10, devices, new LinkedHashSet<String>());
        SceneBusinessValidator noProtection = new SceneBusinessValidator(scene);

        SceneOperation operation = SceneOperation.clearAll("用户说清理一下");

        // Act
        ValidationResult<OperationPreview> result = noProtection.validate(operation);

        // Assert：校验通过 —— 它确实是个能执行的操作。
        assertTrue(result.isValid(), result.getErrorMessage());

        // Assert：预览明确告知后果，2 台全部删除、清空后为 0。
        assertTrue(result.getValue().isDestructive(), "清空必须标记为破坏性");
        assertEquals(2, result.getValue().getDeviceCountBefore());
        assertEquals(0, result.getValue().getDeviceCountAfter());

        // Assert：确认文案要带不可逆警告，这是用户点确认前最后一次提醒。
        assertTrue(result.getValue().toConfirmationMessage().contains("不可逆"),
                "破坏性操作的确认文案必须提示不可逆");
    }

    /** 同一个操作在不同场景下结论可能相反：合法性依赖运行时状态而不是操作的固有属性，所以这一层不能像 Schema 层那样写成纯函数。 */
    @Test
    public void shouldGiveDifferentVerdictForSameOperationInDifferentScenes() {
        // Arrange：同一个操作对象。
        SceneOperation operation = SceneOperation.move("camera-1", 5, 5, "调整位置");

        // Act：在有 camera-1 的场景里校验。
        ValidationResult<OperationPreview> inPopulated = validator().validate(operation);

        // Act：在空场景里校验同一个操作。
        SceneBusinessValidator emptyValidator =
                new SceneBusinessValidator(SceneSnapshot.empty(20, 20, 5));
        ValidationResult<OperationPreview> inEmpty = emptyValidator.validate(operation);

        // Assert：结论相反。操作没变，场景变了。
        assertTrue(inPopulated.isValid(), "有设备的场景里应当合法");
        assertFalse(inEmpty.isValid(), "空场景里同一操作应当非法");
    }

    /** 多个业务问题一次性全部报出：全部问题一次发回模型它一轮就能改对，逐条返回要多花好几轮 token 和时间。 */
    @Test
    public void shouldReportMultipleBusinessErrorsAtOnce() {
        // Arrange：设备不存在 + 坐标越界，两个问题同时存在。
        SceneOperation operation = SceneOperation.move("ghost-1", 99, 99, "移动");

        // Act
        ValidationResult<OperationPreview> result = validator().validate(operation);

        // Assert：两个问题都报出来了。
        assertFalse(result.isValid());
        assertTrue(result.getErrors().size() >= 2,
                "应报出至少两个问题，实际：" + result.getErrors());
    }

    /** {@code null} 操作被安全拒绝而不抛 NPE：校验器是防线，防线自己崩掉，上游任何一处漏检都会变成 500。 */
    @Test
    public void shouldRejectNullOperationSafely() {
        // Act + Assert：返回错误而不是抛异常。
        ValidationResult<OperationPreview> result = validator().validate(null);
        assertFalse(result.isValid());
    }
}
