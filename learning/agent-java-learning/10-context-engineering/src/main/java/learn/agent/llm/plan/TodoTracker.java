package learn.agent.llm.plan;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;

/**
 * 会话级 TODO：用完整计划快照对抗长上下文里的任务遗忘。
 *
 * <p>这是阶段 9 的第一个机制，解决的问题和前八个阶段都不同。前面解决的是
 * 「这一轮怎么跑对」（工具选得对不对、参数合不合法、该不该被允许执行）；
 * 本课解决的是<b>「跑了二十轮之后，它还记得自己要干什么吗」</b>。</p>
 *
 * <h3>长任务失败的真实样子</h3>
 * <p>不是模型突然变笨了，而是它<b>漂移</b>了：第 3 轮它说「我要先建 schema、
 * 再写 endpoints、最后补测试」，到第 18 轮它在反复调整 schema 的字段命名，
 * 已经完全忘了后面两件事。这时候你去问它「你的计划是什么」，它会临时编一个
 * 听起来很合理的新计划 —— 而那不是它 15 轮前定下的那个。</p>
 *
 * <p>解决办法不是把提示词写得更长（阶段 5 已经证明那不管用，见文章第 5 篇
 * 「为什么上下文越长，系统提示词越没用」），而是<b>让计划成为一个必须被反复
 * 重写的显式对象</b>。每次重写都强迫模型把整张表重读一遍。</p>
 *
 * <h3>三条设计决定</h3>
 * <ul>
 *   <li><b>只收完整快照，不收增量补丁。</b>见 {@link TodoWriteValidator} 的说明。
 *       代价是 token，收益是「重读」这个动作本身。</li>
 *   <li><b>状态是会话级的，不落盘。</b>一个 tracker 实例对应一次会话生命周期。
 *       跨会话记忆是本阶段第 4 课（文件记忆）的题目，两者<b>不是一回事</b> ——
 *       混在一起做，就会得到一个既不像计划也不像记忆的东西。</li>
 *   <li><b>陈旧提醒是请求级临时消息，不进历史。</b>见 {@link #beforeModel()}。</li>
 * </ul>
 *
 * <h3>为什么 tracker 自己持有 toolDefinition</h3>
 * <p>{@link #getToolDefinition()} 返回的定义里，handler 是一个绑定到<b>本实例</b>
 * 的闭包。这样做的目的是让「工具」和「状态」在构造时就锁死：注册表拿到的
 * 那个 {@code todo_write}，写入的一定是这个 tracker，不可能因为有人注册错了
 * 而写到另一个会话的计划里。</p>
 */
public class TodoTracker {

    /** 连续多少轮「有工具调用但没更新计划」之后开始提醒。 */
    public static final int STALE_TOOL_ROUNDS = 3;

    /**
     * 提醒文案固定不变。
     *
     * <p>写成常量而不是每次拼一句话，是为了让测试能断言<b>同一个契约</b>。
     * 文案每次都不一样的话，测试只能断言「包含某个关键词」，那种断言在文案
     * 改动时不会失败，也就等于没有守住任何东西。</p>
     */
    public static final String STALE_REMINDER =
            "请保持 TODO 列表是最新的。计划有变化时，调用 todo_write 提交完整的任务快照。";

    /** 工具名。模型在 tool_calls 里回传的就是这个字符串。 */
    public static final String TOOL_NAME = "todo_write";

    /** 序列化快照用。ObjectMapper 线程安全，做成静态常量避免每次写计划都新建。 */
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 当前完整快照。整体替换而不是原地改，保证工具结果和内存状态一一对应。 */
    private List<TodoItem> todos = Collections.emptyList();

    /**
     * 自上次写计划以来，发生了多少轮「调了别的工具」。
     *
     * <p>注意计的是<b>工具轮</b>，不是模型轮。模型只说话不调工具的那些轮次不计数：
     * 那种轮次通常是在解释、在提问、在等用户回答，计划没有推进，也就谈不上陈旧。</p>
     */
    private int nonTodoToolRounds = 0;

    /** 绑定到本实例的工具定义。 */
    private final ToolDefinition toolDefinition;

    public TodoTracker() {
        this.toolDefinition = new ToolDefinition(
                TOOL_NAME,
                "用完整的任务快照替换当前 TODO 列表。计划有任何变化都要调用，"
                        + "每次都要提交全部任务项（包括已完成的），不要只提交变化的部分。",
                buildParametersSchema(),
                // WRITE 而不是 DESTRUCTIVE：改计划是可撤销的（下一次快照就能改回来），
                // 不该每次都拦下来问用户。如果标成 DESTRUCTIVE，第 5 课那道破坏性闸门
                // 会让 todo_write 永远执行不了 —— 计划机制直接失效。
                ToolEffect.WRITE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return writeTodos(arguments);
                    }
                },
                new TodoWriteValidator());
    }

    /**
     * 暴露给 {@link learn.agent.llm.tool.ToolRegistry} 的工具定义。
     *
     * <p>每次返回同一个实例。这一点被第 7 课的第三道锁依赖：那道锁用 {@code !=}
     * 判断「Hook 改过参数之后，工具定义还是不是注册表里那一个」。如果这里每次
     * 新建一个 definition，那道锁会在完全正常的调用上误报。</p>
     */
    public ToolDefinition getToolDefinition() {
        return toolDefinition;
    }

    /** @return 当前计划快照（不可修改） */
    public List<TodoItem> getTodos() {
        return todos;
    }

    /** @return 当前连续未更新计划的工具轮数，主要给测试和调试用 */
    public int getNonTodoToolRounds() {
        return nonTodoToolRounds;
    }

    /**
     * 记录一轮工具调用发生了什么。
     *
     * <p>由循环在每轮工具执行后调用。这一轮里出现了 {@code todo_write} 就重置
     * 计数器，否则累加。</p>
     *
     * <p><b>空列表直接返回</b>：没有工具调用的轮次不参与计数，理由见
     * {@link #nonTodoToolRounds} 的说明。</p>
     *
     * @param toolNames 这一轮调用过的工具名
     */
    public void recordToolRound(List<String> toolNames) {
        if (toolNames == null || toolNames.isEmpty()) {
            return;
        }
        if (toolNames.contains(TOOL_NAME)) {
            nonTodoToolRounds = 0;
            return;
        }
        nonTodoToolRounds += 1;
    }

    /**
     * 生成下一次模型请求要临时附加的消息。
     *
     * <p><b>这是本课最容易被做错的一个方法</b>，两个细节都反直觉：</p>
     *
     * <h4>一、返回值不进消息历史</h4>
     * <p>调用方应该把它拼进<b>这一次</b>请求的消息列表，然后丢掉，
     * 不要 append 进那个跨轮次累积的 {@code messages}。因为提醒是
     * 「此刻需要被看到的一句话」，不是「对话确实发生过的一部分」。
     * 写进历史的后果是：它会在之后<b>每一轮</b>都被重新发送一次，
     * 一直付 token；而且回放这段对话时，会看到一堆用户从没说过的话。</p>
     *
     * <h4>二、取一次就清零</h4>
     * <p>不清零的话，一旦跨过阈值，之后每轮都会注入同一句提醒 —— 模型会看到
     * 五条一模一样的 system 消息，那既浪费 token 又降低这句话的信号强度。
     * 「提醒过了就当已经提醒到了」，下一次陈旧要重新数三轮。</p>
     *
     * <p>副作用写在一个名字像查询的方法里，这一点是<b>可疑</b>的 ——
     * 通常 {@code getXxx}/{@code beforeXxx} 不该改状态。这里保留，理由是
     * 「生成提醒」和「记下已提醒」在语义上是同一件事，拆成两个方法反而会
     * 出现「调了第一个忘了调第二个」的漏洞。方法名用 {@code beforeModel}
     * 而不是 {@code getReminder}，就是为了提示它有时序含义。</p>
     *
     * @return 要临时附加的消息；未达阈值时返回空列表
     */
    public List<ChatMessage> beforeModel() {
        if (nonTodoToolRounds < STALE_TOOL_ROUNDS) {
            return Collections.emptyList();
        }
        nonTodoToolRounds = 0;
        return Collections.singletonList(ChatMessage.system(STALE_REMINDER));
    }

    /**
     * 真正的写入路径。参数已经过 {@link TodoWriteValidator}，这里不再重复校验。
     *
     * <p>整体替换而不是逐项合并：失败路径根本走不到这里（校验不过的话
     * {@code prepare} 阶段就返回错误了），所以不存在「改了一半」的中间状态。</p>
     */
    private ToolExecutionResult writeTodos(JsonNode arguments) {
        JsonNode array = arguments.get("todos");
        List<TodoItem> parsed = new ArrayList<TodoItem>();
        for (int i = 0; i < array.size(); i++) {
            JsonNode item = array.get(i);
            parsed.add(new TodoItem(
                    item.get("content").asText(),
                    TodoStatus.fromWireValue(item.get("status").asText())));
        }

        this.todos = Collections.unmodifiableList(parsed);
        this.nonTodoToolRounds = 0;
        return ToolExecutionResult.success(serializeSnapshot());
    }

    /**
     * 把当前快照序列化成回传给模型的 JSON。
     *
     * <p>为什么要把整张表回传，而不是只回一句「已保存」：这是让模型「重读」
     * 计划的最后一步。模型在下一轮看到的是<b>系统确认后的状态</b> ——
     * 和它自己刚写的那份不一致时（比如某项被 trim 了、或者它写超了上限），
     * 它能立刻发现。</p>
     *
     * <p>为什么回 JSON 而不是 {@link #render()} 那种中文列表：模型刚写进来的
     * 就是 JSON，回一份同构的 JSON 它才能<b>逐字段对比</b>。回中文的话，它得
     * 先把自己那份 JSON 在脑子里翻译一遍再比，这一步翻译本身就可能把差异抹掉。
     * 人类可读的那份留给 {@link #render()} —— 两个受众，两种格式。</p>
     */
    private String serializeSnapshot() {
        ObjectNode root = MAPPER.createObjectNode();
        ArrayNode array = root.putArray("todos");
        for (TodoItem item : todos) {
            // 字段按固定顺序写入，所以同一份计划每次序列化的字节完全一致。
            // 这对模型不是小事：内容没变但字节变了，它会以为计划被人动过。
            ObjectNode node = array.addObject();
            node.put("content", item.getContent());
            node.put("status", item.getStatus().getWireValue());
        }
        return root.toString();
    }

    /**
     * 把当前快照渲染成人类可读文本。
     *
     * <p>给 demo 输出和日志用，<b>不是</b>回传给模型的那份 —— 回传的是
     * {@link #serializeSnapshot()} 产出的 JSON，理由见那里的说明。</p>
     */
    public String render() {
        if (todos.isEmpty()) {
            return "当前 TODO 列表为空。";
        }
        StringBuilder builder = new StringBuilder();
        builder.append("当前 TODO 列表（共 ").append(todos.size()).append(" 项）：\n");
        for (int i = 0; i < todos.size(); i++) {
            TodoItem item = todos.get(i);
            builder.append(i + 1).append(". [").append(item.getStatus().getWireValue())
                    .append("] ").append(item.getContent());
            if (i < todos.size() - 1) {
                builder.append('\n');
            }
        }
        return builder.toString();
    }

    /** @return 已完成项数 */
    public int getCompletedCount() {
        int count = 0;
        for (TodoItem item : todos) {
            if (item.isCompleted()) {
                count++;
            }
        }
        return count;
    }

    /**
     * @return 是否所有项都已完成；空列表返回 false
     *
     * <p>空列表返回 false 是刻意的：「没有计划」和「计划全部完成」是两种完全
     * 不同的状态，前者通常意味着模型压根没建计划。如果这里对空列表返回 true，
     * 调用方就会把「什么都没做」当成「全做完了」。</p>
     */
    public boolean isAllCompleted() {
        return !todos.isEmpty() && getCompletedCount() == todos.size();
    }

    /** {@code todo_write} 的参数 Schema。发给模型时原样塞进请求。 */
    private static String buildParametersSchema() {
        return "{"
                + "\"type\":\"object\","
                + "\"properties\":{"
                + "\"todos\":{"
                + "\"type\":\"array\","
                + "\"description\":\"完整的任务快照，必须包含全部任务项\","
                + "\"maxItems\":" + TodoWriteValidator.MAX_TODOS + ","
                + "\"items\":{"
                + "\"type\":\"object\","
                + "\"properties\":{"
                + "\"content\":{\"type\":\"string\",\"description\":\"任务描述，一句话\"},"
                + "\"status\":{\"type\":\"string\",\"enum\":[\"pending\",\"in_progress\",\"completed\"]}"
                + "},"
                + "\"required\":[\"content\",\"status\"]"
                + "}"
                + "}"
                + "},"
                + "\"required\":[\"todos\"]"
                + "}";
    }
}
