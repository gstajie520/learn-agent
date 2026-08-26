package learn.agent.llm.lesson03;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatRole;
import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.ModelException;
import learn.agent.llm.lesson01.TokenUsage;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 端到端链路测试：自然语言 → 预览。
 *
 * <p>前三个测试类各自验证一层，这个类验证<b>四步串起来</b>的行为：
 * 调模型 → 解析 → 结构校验 → 业务校验 → 预览。</p>
 *
 * <p>覆盖的核心规则：</p>
 * <ul>
 *   <li>成功路径产出预览，且<b>没有修改任何数据</b>；</li>
 *   <li>★ 结构合法但业务非法的输入被拦住（本课最重要的一条）；</li>
 *   <li>模型输出带围栏、带解释文字时仍能处理；</li>
 *   <li>发给模型的请求里带了 Schema 说明和场景现状；</li>
 *   <li>校验失败不抛异常，而是返回可回传给模型的错误；</li>
 *   <li>Token 被累加，失败的那次也算。</li>
 * </ul>
 *
 * <p>全部使用 {@link FakeModelClient}：不要密钥、不要网络，
 * 而且能精确指定「模型这次返回什么」—— 真实模型做不到这一点，
 * 所以这些边界场景只有用 Fake 才测得出来。</p>
 */
public class SceneOperationServiceTest {

    /** 20x20 场景，上限 5 台，已有一台雷达和一台受保护的摄像头。 */
    private SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        devices.put("camera-01", DeviceType.CAMERA);
        return new SceneSnapshot(20, 20, 5, devices,
                java.util.Collections.singleton("camera-01"));
    }

    /**
     * 规则：正常指令走完四步，产出预览，且不修改任何数据。
     *
     * <p><b>为什么重要：</b>这是本课的成功路径，也是核心原则的体现 ——
     * 模型输出的终点是<b>预览</b>，不是数据库写入。用户确认之后才执行，
     * 而"执行"这一步本课刻意不实现。</p>
     *
     * <p><b>违反会怎样：</b>如果这里直接写库，模型的任何误解都会立即
     * 变成真实数据变更。加上模型输出不确定，同一句话两次可能得到不同结果，
     * 出问题后你甚至无法复现。</p>
     */
    @Test
    public void shouldProducePreviewForValidInstruction() {
        // Arrange：模型返回一个完全合法的 create 操作。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":5,\"y\":8,"
                        + "\"reason\":\"用户要求在北侧增加雷达\"}",
                FinishReason.STOP, new TokenUsage(180, 40));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        SceneSnapshot before = scene();

        // Act
        ValidationResult<OperationPreview> result = service.propose("在北侧加一台雷达", before);

        // Assert：校验通过，拿到预览。
        assertTrue(result.isValid(), "应当通过校验，实际错误：" + result.getErrors());
        OperationPreview preview = result.getValue();
        assertEquals(OperationType.CREATE, preview.getOperation().getType());
        assertEquals(DeviceType.RADAR, preview.getOperation().getDeviceType());

        // Assert：预览说明了「确认后会发生什么」——设备数从 2 变 3。
        assertEquals(2, preview.getDeviceCountBefore());
        assertEquals(3, preview.getDeviceCountAfter());
        assertTrue(preview.changesDeviceCount());

        // Assert：★ 场景快照没有被修改。预览不是执行。
        assertEquals(2, before.getDeviceCount());
        assertFalse(before.hasDevice("radar-02"));
    }

    /**
     * 规则：★★ 结构完全合法、但业务非法的输出必须被拦住。
     *
     * <p><b>这是整个第 3 课最重要的一个测试。</b>模型返回的 JSON 挑不出
     * 任何格式问题：字段齐全、类型正确、operation 和 targetId 搭配无误。
     * 用任何 JSON Schema 校验器都会放行。</p>
     *
     * <p>但 {@code radar-99} 在这个场景里<b>不存在</b>。这是模型幻觉最典型的
     * 形态：它不会输出 {@code "targetId": "我不知道"}，而是编一个看起来
     * 很合理的 id。格式校验对此完全无能为力，因为判断它是否存在
     * 需要<b>运行时数据</b>。</p>
     *
     * <p><b>违反会怎样：</b>如果只做 Schema 校验就执行，下游会拿着一个
     * 不存在的 id 去操作数据库。乐观情况是报错，但错误信息会指向数据层，
     * 排查方向完全跑偏 —— 真正的原因在模型输出，不在 SQL。
     * 悲观情况是被当成空条件处理，影响范围扩大到无关数据。</p>
     *
     * <p>这就是「结构正确 ≠ 业务合法」这句话的全部含义。</p>
     */
    @Test
    public void shouldRejectStructurallyValidButNonexistentDevice() {
        // Arrange：JSON 完全合规，只是 radar-99 不存在。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"move\",\"targetId\":\"radar-99\",\"x\":10,\"y\":10,"
                        + "\"reason\":\"用户要求把雷达往东移\"}",
                FinishReason.STOP, new TokenUsage(180, 30));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act
        ValidationResult<OperationPreview> result = service.propose("把雷达移到中间", scene());

        // Assert：被业务层拦住。
        assertFalse(result.isValid(), "不存在的设备必须被拦住");
        assertTrue(result.getErrorMessage().contains("radar-99"));
        assertTrue(result.getErrorMessage().contains("不存在"));

        // Assert：错误信息里列出真实设备清单，模型下一轮才能改对。
        assertTrue(result.getErrorMessage().contains("radar-01"),
                "错误应列出真实设备，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：删除受保护设备必须被拦住，即使指令和 JSON 都合法。
     *
     * <p><b>为什么重要：</b>这是危险操作防线。用户说的话没问题，模型理解也没问题，
     * JSON 更没问题 —— 但这台设备被业务方标记为关键设备。
     * 保护标记由程序维护，模型无权跨过。</p>
     *
     * <p><b>违反会怎样：</b>一句自然语言就能删掉关键设备，
     * 而且这条路径绕过了所有常规审批。删除通常不可逆。</p>
     */
    @Test
    public void shouldBlockDeletionOfProtectedDevice() {
        // Arrange：camera-01 是受保护设备。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"delete\",\"targetId\":\"camera-01\","
                        + "\"reason\":\"用户要求删除这台摄像头\"}",
                FinishReason.STOP, new TokenUsage(150, 20));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act
        ValidationResult<OperationPreview> result = service.propose("把那个摄像头删了", scene());

        // Assert：被拦住，并说明走人工流程。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("camera-01"));
        assertTrue(result.getErrorMessage().contains("保护")
                        || result.getErrorMessage().contains("人工"),
                "应提示受保护或需人工流程，实际：" + result.getErrorMessage());
    }

    /**
     * 规则：模型输出带 ```json 围栏和解释文字时，仍能正常处理。
     *
     * <p><b>为什么重要：</b>这是模型的真实行为，不是异常情况。
     * 即使 system 消息明确要求"不要代码围栏"，模型仍然经常带上 ——
     * 它的训练数据里 JSON 大多是带围栏的。</p>
     *
     * <p><b>违反会怎样：</b>直接 {@code readValue} 会抛
     * {@code Unexpected character '`'}，而这个错误看起来像"模型坏了"，
     * 实际上模型输出的内容完全正确，只是多了包装。</p>
     */
    @Test
    public void shouldHandleFencedAndChattyOutput() {
        // Arrange：围栏 + 前后解释文字，全都是模型的常见习惯。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "好的，我来帮你处理。\n\n```json\n"
                        + "{\"operation\":\"create\",\"deviceType\":\"camera\",\"x\":3,\"y\":4,"
                        + "\"reason\":\"用户要求增加摄像头\"}\n"
                        + "```\n\n希望这样符合你的需求！",
                FinishReason.STOP, new TokenUsage(200, 60));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act
        ValidationResult<OperationPreview> result = service.propose("加个摄像头", scene());

        // Assert：包装被剥掉，内容正常解析。
        assertTrue(result.isValid(), "应当能处理围栏，实际错误：" + result.getErrors());
        assertEquals(DeviceType.CAMERA, result.getValue().getOperation().getDeviceType());
    }

    /**
     * 规则：发给模型的请求必须包含 Schema 说明和场景现状。
     *
     * <p><b>为什么重要：</b>模型不会凭空知道你要什么格式，也不知道
     * 场景里现在有哪些设备。不给场景现状，它只能编 id ——
     * 那就不能怪它幻觉，是提示词没给足信息。</p>
     *
     * <p><b>违反会怎样：</b>模型输出格式随机、id 全靠猜，
     * 校验失败率大幅上升，每次失败都要多花一轮 token 重试。</p>
     *
     * <p>本测试同时验证第 1 课那条规则仍然成立：系统规则和用户输入
     * 是两条独立消息，用户输入没有被拼进 system。</p>
     */
    @Test
    public void shouldSendSchemaAndSceneStateToModel() {
        // Arrange
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"clear_all\",\"reason\":\"用户说清理一下\"}",
                FinishReason.STOP, new TokenUsage(100, 10));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act
        service.propose("全部清空", scene());

        // Assert：两条消息，角色分离。
        ChatRequest sent = fake.getLastRequest();
        assertEquals(2, sent.getMessages().size());
        assertEquals(ChatRole.SYSTEM, sent.getMessages().get(0).getRole());
        assertEquals(ChatRole.USER, sent.getMessages().get(1).getRole());

        // Assert：system 里有格式说明。
        String system = sent.getMessages().get(0).getContent();
        assertTrue(system.contains("operation"), "system 应包含字段说明");
        assertTrue(system.contains("create"), "system 应列出可选操作值");

        // Assert：system 里有场景现状，模型才不用编设备 id。
        assertTrue(system.contains("radar-01"), "system 应包含真实设备清单");
        assertTrue(system.contains("20"), "system 应包含场景边界");

        // Assert：用户原话没有被拼进系统规则。
        assertFalse(system.contains("全部清空"), "用户输入不能进 system 消息");
        assertEquals("全部清空", sent.getMessages().get(1).getContent());

        // Assert：结构化输出要稳定，温度必须低。
        assertTrue(sent.getTemperature() <= 0.2,
                "结构化输出应使用低温度，实际：" + sent.getTemperature());
    }

    /**
     * 规则：校验失败返回错误结果，不抛异常。
     *
     * <p><b>为什么重要：</b>模型输出不合规是<b>预期内</b>的常规情况，不是系统故障。
     * 返回错误对象而不是抛异常，调用方才能把问题回传给模型让它重试 ——
     * 这正是阶段 7 Agent Loop 的基础。</p>
     *
     * <p><b>违反会怎样：</b>用异常表示"模型这次没答对"，会让正常业务流程里
     * 充满 try/catch，而且异常栈里混着模型输出问题和真实系统故障，
     * 监控无法区分二者。</p>
     */
    @Test
    public void shouldReturnErrorResultInsteadOfThrowing() {
        // Arrange：模型漏了必填的 deviceType。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"x\":5,\"y\":5}",
                FinishReason.STOP, new TokenUsage(120, 20));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act：不应抛异常。
        ValidationResult<OperationPreview> result = service.propose("加个东西", scene());

        // Assert：返回失败结果，错误可读且可回传给模型。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("deviceType"));
    }

    /**
     * 规则：模型输出被截断时抛 {@link ModelException}，而不是返回校验失败。
     *
     * <p><b>为什么重要：</b>这里要区分两类失败，它们的处理方式完全不同：</p>
     *
     * <ul>
     *   <li><b>校验失败</b>（返回 {@code ValidationResult.fail}）：模型正常回答了，
     *       但内容不合规。错误可以回传给模型让它改，改完可能就对了；</li>
     *   <li><b>调用失败</b>（抛 {@code ModelException}）：这次请求本身没完成。
     *       截断属于这一类 —— 把「JSON 缺右括号」回传给模型没有意义，
     *       它上次就是因为 token 不够才断的，再说一遍还是会断。
     *       正确做法是调大 {@code maxOutputTokens} 或缩短输入。</li>
     * </ul>
     *
     * <p>这与第 1 课的 {@code SceneSummaryService} 处理 {@code LENGTH} 的方式一致 ——
     * 同一类故障在两课里有同一种语义，不能一处抛异常、一处返回失败。</p>
     *
     * <p><b>违反会怎样：</b>如果截断被当成普通校验失败，调用方会把它塞进
     * 「回传给模型重试」的分支，于是同一个必然失败的请求被重试到用尽次数，
     * 每一轮都真实计费。</p>
     */
    @Test
    public void shouldThrowOnTruncatedModelOutput() {
        // Arrange：JSON 写到一半就到了 token 上限。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"deviceType\":\"rad",
                FinishReason.LENGTH, new TokenUsage(180, 200));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act + Assert：抛异常，且明确指出该怎么修。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.propose("加雷达", scene())
        );
        assertTrue(exception.getMessage().contains("截断"),
                "错误应说明是截断，实际：" + exception.getMessage());

        // Assert：即使这次失败，Token 依然计费，成本统计不能漏。
        assertEquals(380, service.getTotalTokens());
    }

    /**
     * 规则：Token 被累加，包括校验失败的那次调用。
     *
     * <p><b>为什么重要：</b>校验失败不代表没花钱。模型已经生成了输出，
     * token 已经计费。只统计成功调用会低估真实成本 ——
     * 而结构化输出的失败重试恰恰是成本大头。</p>
     */
    @Test
    public void shouldAccumulateTokensIncludingFailedValidations() {
        // Arrange：第一次输出不合规，第二次合规。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("{\"operation\":\"create\"}",
                FinishReason.STOP, new TokenUsage(100, 20));
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":1,\"y\":1,"
                        + "\"reason\":\"用户要求在(1,1)加雷达\"}",
                FinishReason.STOP, new TokenUsage(150, 30));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act：两次调用，第一次会校验失败。
        ValidationResult<OperationPreview> first = service.propose("加雷达", scene());
        ValidationResult<OperationPreview> second = service.propose("在(1,1)加雷达", scene());

        // Assert：第一次失败，第二次成功。
        assertFalse(first.isValid());
        assertTrue(second.isValid());

        // Assert：两次的 token 都计入，失败那次也算。
        assertEquals(250, service.getTotalPromptTokens());
        assertEquals(50, service.getTotalCompletionTokens());
        assertEquals(300, service.getTotalTokens());
    }

    /**
     * 规则：模型调用失败时，异常向上传播而不是伪装成校验失败。
     *
     * <p><b>为什么重要：</b>要区分两件本质不同的事 ——
     * 「模型答得不对」（业务问题，可以让它重试）和
     * 「模型服务不可用」（系统故障，重试也要先等待）。
     * 混在一起会导致：鉴权失败被当成模型输出问题，
     * 系统一直重新提问，而真正的原因是密钥过期。</p>
     */
    @Test
    public void shouldPropagateModelExceptions() {
        // Arrange：密钥无效。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act + Assert：抛出异常，不是返回校验失败。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.propose("加雷达", scene())
        );
        assertEquals(ModelException.ErrorType.AUTHENTICATION, exception.getErrorType());
    }

    /**
     * 规则：空指令在本地被挡住，不浪费一次模型调用。
     *
     * <p><b>为什么重要：</b>空输入不可能产生有意义的操作，
     * 发出去只是白花 token，还可能让模型自由发挥编一个操作出来。</p>
     */
    @Test
    public void shouldRejectBlankInstructionWithoutCallingModel() {
        // Arrange
        FakeModelClient fake = new FakeModelClient();
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act + Assert
        assertThrows(
                IllegalArgumentException.class,
                () -> service.propose("   ", scene())
        );

        // Assert：一次请求都没发。
        assertEquals(0, fake.getCallCount());
    }

    /**
     * 规则：清空空场景要被拦住。
     *
     * <p><b>为什么重要：</b>这是一个「无意义但无害」的操作。拦住它的价值
     * 不在防止破坏，而在<b>暴露理解偏差</b> —— 用户说"清空"说明他以为
     * 场景里有东西，认知和现实不一致，值得提示而不是静默成功。</p>
     */
    @Test
    public void shouldRejectClearAllOnEmptyScene() {
        // Arrange：空场景。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("{\"operation\":\"clear_all\",\"reason\":\"用户说清空\"}",
                FinishReason.STOP, new TokenUsage(80, 10));
        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        // Act
        ValidationResult<OperationPreview> result = service.propose(
                "全部清空", SceneSnapshot.empty(20, 20, 5));

        // Assert：被拦住并说明原因。
        assertFalse(result.isValid());
        assertTrue(result.getErrorMessage().contains("没有设备")
                        || result.getErrorMessage().contains("无需"),
                "应提示场景本来就是空的，实际：" + result.getErrorMessage());
    }
}
