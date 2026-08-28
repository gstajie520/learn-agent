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

    /** 模型输出的终点是预览而不是写库：直接落库的话，模型的任何误解立刻变成真实数据变更，而且同一句话两次结果可能不同，出问题都无法复现。 */
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
     * 结构合法但设备不存在也要拦住：模型幻觉不会写「我不知道」而是编一个像样的 {@code radar-99}，
     * 任何 Schema 校验器都会放行，下游拿着假 id 操作数据库，报错还指向数据层让排查方向跑偏。
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

    /** 保护标记由程序维护、模型无权跨过：否则一句自然语言就能删掉关键设备，绕过全部常规审批，而删除通常不可逆。 */
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

    /** 围栏和解释文字要能剥掉：模型即使被要求「不要围栏」也常带上，直接 {@code readValue} 抛的 {@code Unexpected character '`'} 看着像模型坏了，其实内容完全正确只是多了包装。 */
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

    /** 请求里要带 Schema 说明和场景现状：不给设备清单，模型只能编 id，那不算它幻觉而是提示词没给足信息，代价是格式随机、校验失败率上升、每次失败多烧一轮 token。 */
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

    /** 模型输出不合规属于预期情况所以返回错误结果：用异常表示「这次没答对」会让正常流程塞满 try/catch，且异常栈里模型问题和真实系统故障混在一起，监控分不开。 */
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
     * 截断抛 {@link ModelException} 而不是返回校验失败：把「JSON 缺右括号」回传给模型毫无意义，
     * 它上次就是 token 不够才断的，当成校验失败会让必然失败的请求重试到用尽次数，每轮都真实计费。
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

    /** 校验失败那次的 token 也要累加：模型已经生成过输出、已经计费，只统计成功调用会低估成本，而失败重试恰恰是结构化输出的成本大头。 */
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

    /** 调用失败要向上传播而不是伪装成校验失败：混在一起的话，密钥过期会被当成模型答得不对，系统一遍遍重新提问却永远问不通。 */
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

    /** 空指令在本地就挡住：空输入产生不了有意义的操作，发出去白花 token，还可能让模型自由发挥编一个操作出来。 */
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

    /** 清空空场景要被拦住：拦它不为防破坏而为暴露理解偏差，用户说「清空」说明以为场景里有东西，静默成功就把这个认知错位藏了起来。 */
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
