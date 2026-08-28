package learn.agent.llm.tool;

import java.util.ArrayList;
import java.util.List;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRequest;
import learn.agent.llm.client.ChatResponse;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.ModelClient;
import learn.agent.llm.client.ModelException;
import learn.agent.llm.client.TokenUsage;

/**
 * 工具调用循环的编排器：把「模型请求工具 → 程序执行 → 结果回传」串成一个闭环。
 *
 * <p>这是本课唯一会「跑起来」的类，也是 Agent 的核心骨架。它做的事可以概括成
 * 一个 while 循环：</p>
 *
 * <pre>{@code
 * 1. 把当前消息列表发给模型
 * 2. 模型要么给最终答复（结束），要么给一个 tool_call（继续）
 * 3. 如果是 tool_call：prepare → invoke → 把结果作为 tool 消息追加进列表
 * 4. 回到第 1 步
 * }</pre>
 *
 * <p>三个关键设计，每一个都对应一个「如果不这么做会怎样」：</p>
 * <ul>
 *   <li><b>结果以 TOOL 角色回传，而不是拼进用户消息</b>：模型需要知道
 *       「这是工具的输出」而不是「用户又说了句话」，否则它分不清该信谁。</li>
 *   <li><b>toolCallId 原样带回</b>：模型靠 id 配对，写错一个字符结果就张冠李戴。</li>
 *   <li><b>破坏性工具不执行，只回传「等待确认」</b>：模型没有权限自己删数据，
 *       它只能提出请求，最终决定权在程序（进而在人）手里。</li>
 * </ul>
 *
 * <p>本课用 {@link ModelClient} 接口而不是具体实现，所以测试时注入
 * {@link learn.agent.llm.client.FakeModelClient}，生产时注入
 * {@link learn.agent.llm.client.HttpModelClient}，这个类一行都不用改。</p>
 */
public class ToolCallingService {

    /** 模型名，透传给 {@link ChatRequest}。 */
    private final String model;

    /** 模型客户端，测试注入假实现。 */
    private final ModelClient client;

    /** 工具注册表，决定模型能调什么。 */
    private final ToolRegistry registry;

    /** 程序提供的受控环境，工具执行时从这里拿身份和场景。 */
    private final ToolContext context;

    /** 单次会话允许的最大工具调用轮数，防止模型陷入死循环烧钱。 */
    private final int maxToolRounds;

    public ToolCallingService(String model,
                              ModelClient client,
                              ToolRegistry registry,
                              ToolContext context,
                              int maxToolRounds) {
        if (model == null || model.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能为空");
        }
        if (client == null) {
            throw new IllegalArgumentException("client 不能为空");
        }
        if (registry == null) {
            throw new IllegalArgumentException("registry 不能为空");
        }
        if (context == null) {
            throw new IllegalArgumentException("context 不能为空");
        }
        if (maxToolRounds <= 0) {
            throw new IllegalArgumentException("maxToolRounds 必须为正数");
        }
        this.model = model;
        this.client = client;
        this.registry = registry;
        this.context = context;
        this.maxToolRounds = maxToolRounds;
    }

    /**
     * 跑一轮完整的工具调用循环，返回模型的最终答复。
     *
     * <p>入参是系统规则和用户输入，出参是模型最终说给人听的话。
     * 中间的「模型要调工具、程序执行、结果回传」全部封装在内部。</p>
     *
     * @param systemPrompt 系统规则，例如「你是场景管理助手」
     * @param userInput    用户本轮说的话
     * @return 模型的最终答复文本
     */
    public String run(String systemPrompt, String userInput) {
        // 消息列表是循环里唯一会变的状态：每轮追加 assistant 的 tool_call 和 tool 结果。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(systemPrompt));
        messages.add(ChatMessage.user(userInput));

        for (int round = 0; round < maxToolRounds; round++) {
            ChatResponse response = client.chat(new ChatRequest(model, messages, 0.0, 1024));

            // 截断：模型话没说完，既没有完整答复也没有工具调用。直接终止并如实告知。
            if (response.getFinishReason() == FinishReason.LENGTH) {
                return "（输出被截断，请缩短问题或提高 maxOutputTokens）";
            }

            // 模型要调工具：这是循环继续的唯一原因。
            if (response.getFinishReason() == FinishReason.TOOL_CALLS) {
                ToolCall call = extractToolCall(response);
                if (call == null) {
                    // 协议说 finish_reason=tool_calls，但没给 tool_calls 数组 —— 违约。
                    return "（模型声明要调工具，但没有给出工具调用内容）";
                }
                messages.add(AgentMessage.assistantToolCall(call).toChatMessage());

                // prepare：查工具、解析参数、校验。零副作用，失败也返回结果。
                PreparedToolCall prepared = registry.prepare(call);
                ToolExecutionResult result = executeOrConfirm(prepared);

                // 结果以 TOOL 角色回传，id 原样带回。
                messages.add(AgentMessage.toolResult(call.getId(), result.getContent()).toChatMessage());
                continue;
            }

            // 其余情况（STOP / CONTENT_FILTER / UNKNOWN）：把 content 当最终答复返回。
            return response.getContent();
        }

        // 轮数耗尽：模型一直在调工具，没有给出最终答复。
        return "（达到最大工具调用轮数 " + maxToolRounds + "，仍未得到最终答复）";
    }

    /**
     * 从响应里取出工具调用。
     *
     * <p>第 1 课的 {@link ChatResponse} 没有 toolCalls 字段，本课也不改它。
     * 真实实现里这一步要从响应 JSON 的 {@code tool_calls} 数组解析；
     * 本课为了聚焦「循环」本身，用一个约定来桥接：模型客户端把工具调用
     * 编码进 content 的约定格式，这里再解出来。详见 {@link ToolCallCodec}。</p>
     */
    private ToolCall extractToolCall(ChatResponse response) {
        return ToolCallCodec.decode(response.getContent());
    }

    /**
     * 执行工具，但破坏性工具不执行、只回传「等待确认」。
     *
     * <p>这是「模型能调」和「程序该执行」的分界点：prepare 已经确认了
     * 参数合法，但参数合法不代表可以执行 —— 删设备这种不可逆操作，
     * 必须有人点头。本课用「回传等待确认」表达这个停顿，阶段 8 会把它
     * 扩展成真正的审批流。</p>
     */
    private ToolExecutionResult executeOrConfirm(PreparedToolCall prepared) {
        if (prepared.isFailed()) {
            // 准备阶段就失败了（工具不存在 / 参数非法），直接回传错误。
            return prepared.getError();
        }
        ToolDefinition definition = prepared.getDefinition();
        if (definition.getEffect().requiresConfirmation()) {
            // 破坏性工具：不执行，把「等待确认」作为结果回传，让模型转述给用户。
            return ToolExecutionResult.success(
                    "工具 " + definition.getName() + " 需要人工确认后才能执行，"
                            + "请向用户说明将要进行的操作并等待确认。");
        }
        return registry.invoke(prepared, context);
    }
}