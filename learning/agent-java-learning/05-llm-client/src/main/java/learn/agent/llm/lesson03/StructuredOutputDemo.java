package learn.agent.llm.lesson03;

import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.TokenUsage;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * 阶段 5 第 3 课的教学入口。
 *
 * <p>按业务顺序演示八个场景。核心要看清一件事：</p>
 *
 * <p><b>结构正确 ≠ 业务合法。</b>场景五到场景七的 JSON 都<b>完全合法</b>，
 * 前三层校验全部通过，但业务上一个都不能执行。</p>
 *
 * <p>运行：</p>
 * <pre>
 * [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 * mvn -o -pl 05-llm-client -am package -DskipTests
 * java "-Dfile.encoding=UTF-8" -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.lesson03.StructuredOutputDemo
 * </pre>
 */
public class StructuredOutputDemo {

    public static void main(String[] args) {
        SceneSnapshot scene = buildScene();
        System.out.println("当前场景：" + scene);
        System.out.println("受保护设备：" + scene.getProtectedDeviceIds() + "（不允许通过自然语言删除）");
        System.out.println();

        demoHappyPath(scene);
        demoCodeFence(scene);
        demoNotJson(scene);
        demoSchemaViolation(scene);
        demoDeviceNotFound(scene);
        demoOutOfBounds(scene);
        demoProtectedDevice(scene);
        demoPreviewDoesNotMutate(scene);
    }

    /** 场景一：四步全部通过。 */
    private static void demoHappyPath(SceneSnapshot scene) {
        System.out.println("=== 场景一：四步全部通过 ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":10,\"y\":20,"
                        + "\"reason\":\"用户要求在北侧增加雷达\"}",
                FinishReason.STOP,
                new TokenUsage(220, 40));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("在北侧放一台雷达", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println(result.getValue().toConfirmationMessage());
        System.out.println("模型给的理由：" + result.getValue().getOperation().getReason());
        System.out.println("要点：模型输出的是数据，不是文本。程序可以直接执行它。");
        System.out.println();
    }

    /** 场景二：模型爱用代码围栏，解析层必须容忍。 */
    private static void demoCodeFence(SceneSnapshot scene) {
        System.out.println("=== 场景二：模型把 JSON 包在代码围栏里 ===");

        FakeModelClient fake = new FakeModelClient();
        // 这是真实模型极常见的行为：即使系统规则说了「不要代码围栏」，它依然会加，
        // 因为训练数据里 JSON 几乎总是被围栏包着。
        fake.enqueueResponse(
                "好的，这是操作：\n```json\n{\"operation\":\"delete\",\"targetId\":\"cam-01\","
                        + "\"reason\":\"用户要求移除东侧摄像头\"}\n```\n希望有帮助！",
                FinishReason.STOP,
                new TokenUsage(220, 35));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("删掉那个摄像头", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("预览：" + result.getValue().getSummary());
        System.out.println("要点：提示词里写了「不要围栏」也挡不住，因为模型是概率的。");
        System.out.println("     所以解析层要主动剥壳，而不是指望提示词一定生效。");
        System.out.println();
    }

    /** 场景三：根本不是 JSON。 */
    private static void demoNotJson(SceneSnapshot scene) {
        System.out.println("=== 场景三：模型答非所问 ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "好的，我来帮您在北侧添加一台雷达设备。请问需要设置朝向吗？",
                FinishReason.STOP,
                new TokenUsage(220, 30));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("在北侧放一台雷达", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("卡在第 2 步：" + result.getErrorMessage());
        System.out.println("要点：模型「很有礼貌地」违反了格式要求。这在生产里天天发生。");
        System.out.println("     注意它没有报错，是正常回答 —— 只是不是我们要的格式。");
        System.out.println();
    }

    /** 场景四：JSON 合法，但字段搭配不对。 */
    private static void demoSchemaViolation(SceneSnapshot scene) {
        System.out.println("=== 场景四：JSON 合法，但字段不对 ===");

        FakeModelClient fake = new FakeModelClient();
        // 这段 JSON 语法完全正确，Jackson 能解析。
        // 但 operation 是编造的值，而且缺 deviceType 和坐标。
        fake.enqueueResponse(
                "{\"operation\":\"add\",\"device\":\"radar\",\"rotation\":90}",
                FinishReason.STOP,
                new TokenUsage(220, 32));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("在北侧放一台雷达", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("卡在第 2/3 步，一次报出全部问题：");
        for (String error : result.getErrors()) {
            System.out.println("  - " + error);
        }
        System.out.println("要点：JSON 能解析 ≠ 结构合法。模型会自信地编造枚举值和字段。");
        System.out.println("     一次全报出来，模型下一轮就能改对，不用来回几次。");
        System.out.println();
    }

    /** 场景五：结构完全合法，但设备不存在。本课最关键的场景。 */
    private static void demoDeviceNotFound(SceneSnapshot scene) {
        System.out.println("=== 场景五：结构合法，但设备不存在 ★ ===");

        FakeModelClient fake = new FakeModelClient();
        // 这段 JSON 无可指摘：operation 合法、targetId 是非空字符串。
        // 前三层校验 100% 通过。但 radar-99 在场景里不存在。
        fake.enqueueResponse(
                "{\"operation\":\"delete\",\"targetId\":\"radar-99\","
                        + "\"reason\":\"用户说删掉那台雷达\"}",
                FinishReason.STOP,
                new TokenUsage(220, 28));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("把那台旧雷达删掉", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("卡在第 4 步：" + result.getErrorMessage());
        System.out.println("要点：★ 这就是「结构正确不代表业务合法」。");
        System.out.println("     模型不知道场景里有什么，它是在猜 id（幻觉）。");
        System.out.println("     Schema 校验无论多严格都拦不住 —— 因为「有哪些设备」");
        System.out.println("     是运行时数据，不在 Schema 的表达能力范围内。");
        System.out.println();
    }

    /** 场景六：结构合法，但坐标越界。 */
    private static void demoOutOfBounds(SceneSnapshot scene) {
        System.out.println("=== 场景六：结构合法，但坐标越界 ===");

        FakeModelClient fake = new FakeModelClient();
        // x=9999 是合法整数。同一个坐标在 10000x10000 的场景里合法，
        // 在这个 200x200 的场景里非法 —— 合法性取决于运行时数据。
        fake.enqueueResponse(
                "{\"operation\":\"create\",\"deviceType\":\"camera\",\"x\":9999,\"y\":50,"
                        + "\"reason\":\"用户要求在很远的东侧加摄像头\"}",
                FinishReason.STOP,
                new TokenUsage(220, 34));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("在很远的东边放个摄像头", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("卡在第 4 步：" + result.getErrorMessage());
        System.out.println("要点：9999 是合法整数，结构校验挑不出毛病。");
        System.out.println("     「场景多大」是业务知识，只有业务校验层知道。");
        System.out.println();
    }

    /** 场景七：删除受保护设备被拦住。 */
    private static void demoProtectedDevice(SceneSnapshot scene) {
        System.out.println("=== 场景七：删除受保护的关键设备 ★ ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"delete\",\"targetId\":\"fence-main\","
                        + "\"reason\":\"用户要求清理场景\"}",
                FinishReason.STOP,
                new TokenUsage(220, 30));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");
        ValidationResult<OperationPreview> result = service.propose("把场景清理一下", scene);

        System.out.println("通过吗：" + result.isValid());
        System.out.println("卡在第 4 步：" + result.getErrorMessage());
        System.out.println("要点：★ 用户说「清理一下」，模型理解成删除关键设备。");
        System.out.println("     这条约束【不能只写在提示词里】——");
        System.out.println("     提示词是「请求」，模型可能不遵守；代码校验才是「保证」。");
        System.out.println();
    }

    /** 场景八：预览不修改数据。 */
    private static void demoPreviewDoesNotMutate(SceneSnapshot scene) {
        System.out.println("=== 场景八：预览不碰真实数据 ★ ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "{\"operation\":\"delete\",\"targetId\":\"cam-01\","
                        + "\"reason\":\"用户确认删除东侧摄像头\"}",
                FinishReason.STOP,
                new TokenUsage(220, 28));

        SceneOperationService service = new SceneOperationService(fake, "deepseek-v4-flash");

        System.out.println("调用前设备数：" + scene.getDeviceCount() + "，" + scene.describeDeviceIds());
        ValidationResult<OperationPreview> result = service.propose("删掉摄像头 cam-01", scene);
        System.out.println("预览：" + result.getValue().getSummary());
        System.out.println("调用后设备数：" + scene.getDeviceCount() + "，" + scene.describeDeviceIds());

        System.out.println();
        System.out.println("要点：★ cam-01 还在。校验通过只意味着「这个操作可以做」，");
        System.out.println("     不意味着「已经做了」。真正执行必须等用户确认，");
        System.out.println("     并且走另一条独立路径。");
        System.out.println();
        System.out.println("为什么这条边界不能省：模型会误解意图、会被用户诱导、");
        System.out.println("会把「看一下」理解成「删掉」。这不是 bug，是概率模型的固有属性，");
        System.out.println("靠改提示词无法根除，只能靠程序侧的确认环节兜住。");
        System.out.println();
        System.out.println("本次累计 Token：" + service.getTotalTokens());
    }

    /**
     * 构造一个固定的测试场景。
     *
     * <p>200x200 的区域，3 台设备，其中 {@code fence-main} 受保护。</p>
     */
    private static SceneSnapshot buildScene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("cam-02", DeviceType.CAMERA);
        devices.put("fence-main", DeviceType.FENCE);

        Set<String> protectedIds = new LinkedHashSet<String>();
        protectedIds.add("fence-main");

        return new SceneSnapshot(200, 200, 20, devices, protectedIds);
    }
}
