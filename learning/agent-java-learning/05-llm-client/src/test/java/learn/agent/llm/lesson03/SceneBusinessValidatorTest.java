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

    /**
     * 规则：合法的新增操作通过校验，并生成预览。
     *
     * <p><b>为什么重要：</b>先确认正常路径能走通。校验器只会拒绝不该做的事，
     * 不能把合法操作也拦住 —— 那样用户会觉得功能坏了。</p>
     *
     * <p>重点看返回值：拿到的是 {@link OperationPreview}，<b>不是</b>「已完成」。
     * 场景数据一个字节都没改。这是本课最后一道安全边界：
     * 即使前面所有校验都被绕过，真正的修改仍然需要用户点确认。</p>
     */
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

    /**
     * 规则：★ 移动一个不存在的设备必须被拒绝。
     *
     * <p><b>为什么重要：</b>这是<b>模型幻觉最典型的形态</b>，也是本课的核心示例。
     * 模型会自信地编出 {@code device-99} 这样的 id —— 格式完全正确、
     * 命名风格也对，Schema 校验百分之百通过。但场景里根本没有这台设备。</p>
     *
     * <p>模型编 id 不是因为它「坏」，而是因为它<b>没有场景的真实状态</b>。
     * 它只看到用户说「把那台雷达移过去」，就按训练时见过的命名习惯生成一个。</p>
     *
     * <p><b>违反会怎样：</b>操作发到数据层，要么外键报错（幸运情况，用户看到
     * 一个看不懂的数据库异常），要么更新了 0 行然后返回「成功」——
     * 用户以为设备移动了，实际什么都没发生。第二种更糟，因为它是静默的。</p>
     *
     * <p>注意错误信息里列出了当前场景的真实设备 id。这是给模型的<b>纠错线索</b>：
     * 下一轮它就能从真实列表里选，而不是继续猜。</p>
     */
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

    /**
     * 规则：删除不存在的设备必须被拒绝。
     *
     * <p><b>为什么重要：</b>和上一条同源，但后果更严重 —— 删除是不可逆的。
     * 如果下游把「目标不存在」错误处理成「条件不匹配所以不加过滤」，
     * 就会变成全表删除。</p>
     */
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

    /**
     * 规则：★ 删除受保护设备必须被拒绝，即使设备确实存在。
     *
     * <p><b>为什么重要：</b>这是<b>危险操作拦截</b>，和「设备不存在」是不同性质的
     * 防护。设备真实存在、id 完全正确、结构无可挑剔 —— 但业务规定这台设备
     * 不允许通过自然语言指令删除。</p>
     *
     * <p>为什么需要这条：自然语言是模糊的。用户说「把不用的都删了」，
     * 模型判断哪台「不用」靠的是猜测。关键设备（主雷达、消防联动）
     * 一旦被误删，恢复成本远高于让用户多点一次确认。</p>
     *
     * <p><b>违反会怎样：</b>模型的一次误判造成不可逆的生产损失。
     * 而且这类问题在测试环境很难发现 —— 测试场景里没有「关键设备」的概念。</p>
     *
     * <p>保护标记必须由<b>业务方</b>维护，模型无权跨过。这也是
     * 「模型决策 / 程序控制」边界的具体落点：模型可以<b>建议</b>删除，
     * 但能不能删由程序说了算。</p>
     */
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

    /**
     * 规则：★ 坐标超出当前场景边界必须被拒绝。
     *
     * <p><b>为什么重要：</b>这条最能说明两层校验的差别。
     * Schema 层<b>无法</b>判断这个问题 —— 它只能检查「x 是不是整数」，
     * 但「50 这个坐标在不在场景里」取决于场景多大。
     * 20x20 的场景里 (50,50) 越界，100x100 的场景里完全合法。</p>
     *
     * <p><b>违反会怎样：</b>设备被放到用户看不见的位置。前端画布渲染不出来，
     * 用户以为操作失败又点一次，于是产生多台幽灵设备。</p>
     */
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

    /**
     * 规则：边界值 {@code (0,0)} 和 {@code (width-1, height-1)} 是合法的。
     *
     * <p><b>为什么重要：</b>边界条件最容易写错成 {@code <=} 或 {@code <}。
     * 本课约定合法范围是 {@code [0, width)}，和数组下标一样。
     * 如果把右边界也算合法，设备会被放到场景外一格。</p>
     */
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

    /**
     * 规则：负坐标必须被拒绝。
     *
     * <p><b>为什么重要：</b>模型可能输出 -1 表示「往左一点」。
     * 负数在数组下标语境下会直接抛异常，必须在校验层挡住。</p>
     */
    @Test
    public void shouldRejectNegativeCoordinates() {
        // Act
        ValidationResult<OperationPreview> result = validator().validate(
                SceneOperation.create(DeviceType.RADAR, -1, 5, "往左移"));

        // Assert
        assertFalse(result.isValid());
    }

    /**
     * 规则：★ 场景已满时不允许继续新增。
     *
     * <p><b>为什么重要：</b>容量是<b>运行时状态</b>，Schema 层同样看不到。
     * 而且这条防的是一类特定风险：模型在多轮对话里可能反复新增，
     * 每一次单独看都合法，累积起来把场景撑爆。</p>
     *
     * <p><b>违反会怎样：</b>前端渲染卡死，或者存储成本失控。
     * 更麻烦的是这种问题往往在演示时不出现，上线跑一段时间才爆。</p>
     */
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

    /**
     * 规则：移动到有效位置的存在设备通过校验，预览显示设备数量不变。
     *
     * <p><b>为什么重要：</b>移动不改变设备总数。预览里的「前后数量」
     * 是用户判断影响范围的依据，算错会让人误以为设备被复制或丢失。</p>
     */
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

    /**
     * 规则：合法的删除操作通过校验，但预览必须标记为破坏性。
     *
     * <p><b>为什么重要：</b>删除通过校验不等于可以静默执行。
     * {@code isDestructive()} 是给前端的信号：这类操作要用更强的确认方式
     * （二次弹窗、输入设备名确认），不能和新增用同一个「确定」按钮。</p>
     *
     * <p>把「危险程度」放进预览对象，而不是让前端根据操作类型自己判断，
     * 是为了让规则只有一处定义 —— 加新操作类型时不会漏掉前端。</p>
     */
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

    /**
     * 规则：★ 场景里只要有受保护设备，{@code clear_all} 就整体拒绝，而不是「删掉其余的」。
     *
     * <p><b>为什么重要：</b>{@code clear_all} 是本课最危险的操作 ——
     * 它不需要任何参数，所以<b>结构上永远合法</b>，Schema 层拦不住任何东西。
     * 这里是唯一能拦住它的地方。</p>
     *
     * <p><b>为什么整体拒绝而不是部分执行：</b>用户说「清空」时，
     * 他很可能根本没意识到场景里有关键设备。如果删掉其余、留下受保护的，
     * 会产生一个用户完全没预期的中间状态 —— 他以为清空了，实际还剩几台；
     * 而已经删掉的那些又找不回来。直接拒绝并要求逐台指定，
     * 比留下一个半成品状态更安全。</p>
     *
     * <p><b>违反会怎样：</b>「部分成功」是分布式和批量操作里最难排查的一类故障。
     * 用户看到操作「成功」，实际结果和预期不同，而且不可逆。</p>
     */
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

    /**
     * 规则：★ 没有受保护设备时清空可以通过，但预览必须标记破坏性并显示清空后为 0。
     *
     * <p><b>为什么重要：</b>这是「预览而非执行」这个设计的最强论据。
     * 用户说「把这些清理一下」，模型理解成清空整个场景 ——
     * 这个理解不算离谱，但如果直接执行，用户的全部工作瞬间消失。
     * 有了预览，用户看到「将删除全部 2 台设备」就会立刻发现偏差。</p>
     *
     * <p>注意这里校验是<b>通过</b>的：这个操作确实合法可执行。
     * 挡住它不是校验的职责，而是用户确认这一步的职责。
     * 校验层的任务是把后果说清楚，让用户有判断依据。</p>
     */
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

    /**
     * 规则：同一个操作在不同场景下结论可能不同。
     *
     * <p><b>为什么重要：</b>这条集中说明业务校验的本质 ——
     * 它的结论<b>依赖运行时状态</b>，不是操作本身的固有属性。</p>
     *
     * <p>同一个「移动 camera-1」操作：在有 camera-1 的场景里合法，
     * 在空场景里非法。这就是为什么这一层不能像 Schema 层那样写成纯函数，
     * 也是为什么它的测试必须准备场景数据。</p>
     */
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

    /**
     * 规则：多个业务问题一次性全部报出。
     *
     * <p><b>为什么重要：</b>和 Schema 层同理 —— 把全部问题一次发回模型，
     * 它一轮就能改对。逐条返回要多花好几轮 token 和时间。</p>
     */
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

    /**
     * 规则：{@code null} 操作被安全拒绝，不抛 NPE。
     *
     * <p><b>为什么重要：</b>校验器是防线。防线自己崩掉，
     * 上游任何一处漏检都会变成 500 错误。</p>
     */
    @Test
    public void shouldRejectNullOperationSafely() {
        // Act + Assert：返回错误而不是抛异常。
        ValidationResult<OperationPreview> result = validator().validate(null);
        assertFalse(result.isValid());
    }
}
