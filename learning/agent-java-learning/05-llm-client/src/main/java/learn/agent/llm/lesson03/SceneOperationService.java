package learn.agent.llm.lesson03;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.ModelClient;
import learn.agent.llm.lesson01.ModelException;
import learn.agent.llm.lesson01.TokenUsage;

import java.util.ArrayList;
import java.util.List;

/**
 * 把自然语言变成<b>受校验的操作预览</b>。
 *
 * <p>这是第 3 课的主角，也是整个课程从「聊天机器人」转向「Agent 应用」的分界点。
 * 前两课的产出是一段<b>给人看的文本</b>，这一课的产出是一个
 * <b>程序能执行的操作</b> —— 责任完全不同了。文本说错了用户自己会判断，
 * 操作做错了数据就变了。</p>
 *
 * <h2>四步链路</h2>
 *
 * <pre>{@code
 * 自然语言
 *   ↓ 1. 调模型            ModelClient（第 1、2 课的接口，一行没改）
 * 模型输出文本
 *   ↓ 2. 解析              OperationJsonParser      ——「是不是 JSON、字段类型对不对」
 * SceneOperation
 *   ↓ 3. 结构校验          OperationSchemaValidator ——「字段搭配对不对」
 * SceneOperation
 *   ↓ 4. 业务校验          SceneBusinessValidator   ——「业务上能不能做」
 * OperationPreview（只是预览，没有任何副作用）
 * }</pre>
 *
 * <p>四步<b>缺一不可</b>，顺序也不能换。跳过第 3 步，业务校验会在字段不全的
 * 对象上抛 NPE；跳过第 4 步，模型就能删除不存在的设备、把设备放到场景外，
 * 或者一句话清空整个场景。</p>
 *
 * <h2>最重要的一件事：这个类不修改任何数据</h2>
 *
 * <p>它的返回值是 {@link OperationPreview} —— 一份「将会发生什么」的说明。
 * 真正的修改必须由用户确认后，走另一条独立路径执行。</p>
 *
 * <p>为什么这条边界值得反复强调：模型有几个后端从没遇到过的特性 ——
 * 它会误解意图、会把「检查一下」理解成「删掉」、会被用户诱导。
 * 这些不是 bug，是概率模型的固有属性，靠改提示词无法根除。
 * 所以安全边界只能放在<b>程序侧</b>：让模型输出必须经过校验，
 * 并且<b>永远不直接触达真实数据</b>。</p>
 *
 * <p>这也是面试里最能体现工程判断的一点：不是「我接了大模型」，
 * 而是「我假设模型会出错，并让系统在它出错时依然安全」。</p>
 */
public class SceneOperationService {

    private final ModelClient modelClient;

    private final String model;

    private final OperationJsonParser parser = new OperationJsonParser();

    private final OperationSchemaValidator schemaValidator = new OperationSchemaValidator();

    /** 累计输入 Token。结构化输出的系统提示很长，输入成本值得单独观测。 */
    private int totalPromptTokens;

    /** 累计输出 Token。 */
    private int totalCompletionTokens;

    public SceneOperationService(ModelClient modelClient, String model) {
        if (modelClient == null) {
            throw new IllegalArgumentException("modelClient 不能为空");
        }
        if (model == null || model.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能为空");
        }
        this.modelClient = modelClient;
        this.model = model;
    }

    /**
     * 把一句自然语言指令转成操作预览。
     *
     * @param instruction 用户指令，例如「在北侧放一台雷达」
     * @param scene       当前场景快照；业务校验需要它判断设备是否存在、坐标是否越界
     * @return 成功时携带 {@link OperationPreview}，失败时携带卡在哪一步的说明
     * @throws ModelException 模型调用本身失败，或输出被截断
     */
    public ValidationResult<OperationPreview> propose(String instruction, SceneSnapshot scene) {
        if (instruction == null || instruction.trim().isEmpty()) {
            // 空输入不必发请求：省一次费用，也避免模型自由发挥。
            throw new IllegalArgumentException("指令不能为空");
        }
        if (scene == null) {
            // 没有场景快照就无法做业务校验。宁可拒绝，也不做「没校验的操作」。
            // 这是 fail-closed：安全相关的校验拿不到依据时必须拒绝，不能放行。
            throw new IllegalArgumentException("场景快照不能为空，业务校验需要它");
        }

        // 第 1 步：调模型。用的是第 1 课定义的接口，
        // 所以这里可以注入 Fake（测试）或 HTTP 实现（第 2 课），本类无需改动。
        ChatResponse response = callModel(instruction, scene);
        recordUsage(response.getUsage());

        // 拿到响应先看结束原因 —— 第 1 课的规则在这里同样适用，
        // 而且在结构化输出场景下危害更大：
        // 一段残缺的中文人眼能看出来，一段残缺的 JSON 只会解析失败，
        // 更糟的情况是「恰好」能解析成一个字段不全的对象。
        if (response.getFinishReason() == FinishReason.LENGTH) {
            throw new ModelException(
                    ModelException.ErrorType.INVALID_REQUEST,
                    "模型输出被截断，JSON 不完整，需要调大 maxOutputTokens",
                    response.getRequestId(),
                    null);
        }

        // 第 2 步：解析成领域对象（检查 JSON 合法性和字段类型）。
        ValidationResult<SceneOperation> parsed = parser.parse(response.getContent());
        if (!parsed.isValid()) {
            return ValidationResult.fail(parsed.getErrors());
        }

        // 第 3 步：结构校验（检查字段搭配）。
        ValidationResult<SceneOperation> structural = schemaValidator.validate(parsed.getValue());
        if (!structural.isValid()) {
            return ValidationResult.fail(structural.getErrors());
        }

        // 第 4 步：业务校验（对照真实场景）。
        // 到这里对象结构已经完全合法，但业务上仍可能完全不能做 ——
        // 这就是「结构正确 ≠ 业务合法」。
        SceneBusinessValidator businessValidator = new SceneBusinessValidator(scene);
        return businessValidator.validate(structural.getValue());
    }

    /** 调模型：温度设为 0，结构化输出不需要任何创造性。 */
    private ChatResponse callModel(String instruction, SceneSnapshot scene) {
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(buildSystemRule(scene)));
        messages.add(ChatMessage.user(instruction));
        // temperature=0：同样的指令应当尽量得到同样的 JSON。
        // 这和第 1 课的总结任务（0.2）不同 —— 那里允许措辞变化，这里不允许。
        // 高温度会让模型在格式上「发挥创意」，直接降低解析成功率。
        return modelClient.chat(new ChatRequest(model, messages, 0.0, 300));
    }

    /**
     * 组装系统规则：格式说明 + 当前场景状态。
     *
     * <p>格式说明直接取自 {@link OperationSchemaValidator#schemaDescription()}，
     * 这样校验规则和告诉模型的规则来自<b>同一处</b>，不会各改一半。</p>
     *
     * <h2>为什么必须把场景状态也告诉模型</h2>
     *
     * <p>这一点很容易漏，漏了的后果也很典型。模型如果不知道场景里有哪些设备，
     * 用户说「把那台雷达往东移」时它<b>只能编一个 id</b>，比如 {@code device-1}。
     * 编出来的 id 一定过不了业务校验，于是这一轮 token 白花。</p>
     *
     * <p>换句话说：业务校验能<b>兜住</b>模型的幻觉，但兜住不等于没有代价。
     * 把真实设备清单和边界给模型，是从源头降低幻觉率 ——
     * 校验是最后一道防线，不是省掉上下文的理由。</p>
     *
     * <p>代价也要讲清楚：场景状态会占输入 token，而且随设备数量增长。
     * 设备成百上千时不能全量塞进 prompt，要改成先检索相关设备再给模型
     * （这正是阶段 10 RAG 要解决的问题）。本课设备很少，可以直接全给。</p>
     *
     * <p>注意用户输入永远不会拼进这段文本 —— 它是独立的 user 消息。
     * 否则用户可以写「忽略上面的格式要求」来绕过约束。</p>
     */
    private String buildSystemRule(SceneSnapshot scene) {
        StringBuilder sb = new StringBuilder();
        sb.append("你是场景编辑助手。把用户的自然语言指令转换成一个 JSON 操作对象。\n\n");
        sb.append(OperationSchemaValidator.schemaDescription());
        sb.append("\n\n当前场景状态（请只操作真实存在的设备，不要虚构 id）：\n");
        sb.append("  边界：").append(scene.describeBounds()).append("\n");
        sb.append("  设备数：").append(scene.getDeviceCount())
          .append(" / ").append(scene.getMaxDevices()).append("\n");
        sb.append("  设备清单：").append(scene.describeDeviceIds()).append("\n");
        if (!scene.getProtectedDeviceIds().isEmpty()) {
            // 受保护设备提前告知，可以避免模型生成注定被拒绝的删除操作。
            sb.append("  受保护设备（不可删除）：").append(scene.getProtectedDeviceIds()).append("\n");
        }
        return sb.toString();
    }

    private void recordUsage(TokenUsage usage) {
        totalPromptTokens += usage.getPromptTokens();
        totalCompletionTokens += usage.getCompletionTokens();
    }

    public int getTotalPromptTokens() {
        return totalPromptTokens;
    }

    public int getTotalCompletionTokens() {
        return totalCompletionTokens;
    }

    /** 累计总 Token，用于成本核算。 */
    public int getTotalTokens() {
        return totalPromptTokens + totalCompletionTokens;
    }
}
