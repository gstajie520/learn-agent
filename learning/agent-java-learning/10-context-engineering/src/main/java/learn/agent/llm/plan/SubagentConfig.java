package learn.agent.llm.plan;

import learn.agent.llm.hook.HookRegistry;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.PermissionPolicy;

/**
 * 一次委派的全部配置。
 *
 * <p>这个类存在的意义是把两组东西<b>在类型上分开</b>：</p>
 *
 * <table border="1">
 *   <caption>父子之间共享什么、隔离什么</caption>
 *   <tr><th>字段</th><th>父子关系</th><th>为什么</th></tr>
 *   <tr><td>{@code modelFactory}</td><td><b>隔离</b>（每次新建）</td>
 *       <td>共享实例会让两个子任务的响应队列、重试计数互相污染</td></tr>
 *   <tr><td>{@code toolsFactory}</td><td><b>隔离</b>（每次新建）</td>
 *       <td>共享注册表会让一个子任务注册的工具泄漏给下一个</td></tr>
 *   <tr><td>{@code hooks}</td><td><b>共享</b></td>
 *       <td>脱敏、审计这类横切规则对子 Agent 同样必须生效</td></tr>
 *   <tr><td>{@code policy}</td><td><b>共享</b></td>
 *       <td>见下方「为什么权限必须共享」</td></tr>
 * </table>
 *
 * <h3>hooks 和 policy 都不允许传 null</h3>
 * <p>两个字段都是治理边界，传 null 读起来都像「子 Agent 不受这一层管」——
 * 恰好是本课要否定的那句话。没有规则时传<b>空实例</b>
 * （{@code new HookRegistry()}、{@code new PermissionPolicy()}）：
 * 那表达的是「受管，只是当前没有规则」，和「不受管」是两件事。</p>
 *
 * <p><b>这里原先允许 policy 为 null，是一个错误，现已改掉。</b>当时的理由是
 * 「null 表示本次不启用权限系统，语义明确」。它对<b>父</b> Agent 勉强成立，
 * 对子 Agent 不成立，原因有两层：</p>
 * <ol>
 *   <li><b>空策略和没有策略不是一回事。</b>空的 {@link PermissionPolicy} 仍然会
 *       跑完整个裁决：{@code DESTRUCTIVE} 默认 ask、受保护设备硬边界照样求值。
 *       而 policy 为 null 时 {@code HookedAgentLoop} <b>整段跳过裁决</b> ——
 *       连兜底闸门都要靠一个 else 分支补，而那个 else 曾经漏掉过。</li>
 *   <li><b>子 Agent 的 policy 是调用方传的。</b>父 Agent 有策略、调用方给子
 *       Agent 传 null，正是本类下方「为什么权限必须共享」要堵死的提权路径。
 *       允许 null 等于把那道门留了一条缝，而且缝开在类型系统看不见的地方。</li>
 * </ol>
 *
 * <h3>模型名和 trace id 也在这里</h3>
 * <p>{@code model} 和 {@code traceIdGenerator} 不是父子共享/隔离的取舍，
 * 而是「子 Agent 用哪个模型、trace 怎么生成」这两个纯配置项。放在这里是为了让
 * {@link SubagentTool} 只依赖一个参数 —— 委派需要的全部信息都在 config 里，
 * 不会出现「模型名从构造参数来、工具从 config 来」这种两个来源的割裂。</p>
 *
 * <h3>为什么权限必须共享</h3>
 * <p>如果子 Agent 能拿到一份更宽松的策略，那么「委派」就成了<b>提权路径</b>：
 * 父 Agent 删不掉受保护设备，但它可以派一个子 Agent 去删。这不是理论风险 ——
 * 提示词注入的标准手法就是让模型「换个身份再试一次」。</p>
 *
 * <p>所以子 Agent 的权限<b>不会比父 Agent 更宽</b>。它也不会更窄：本课不做
 * 分级授权，那需要「按委派深度收紧策略」的机制，是另一个话题。</p>
 *
 * <h3>子 Agent 不是沙箱</h3>
 * <p>本课的「隔离」<b>只指消息历史隔离</b>。父子跑在同一个 JVM、同一个
 * {@code ToolContext}（同一身份、同一场景）、同一组 Hook 和同一份权限策略。
 * 子 Agent 写下的副作用<b>会保留</b>。它解决的是上下文污染，不提供任何
 * 系统级隔离 —— 把它当沙箱用是这一课最危险的误读。</p>
 */
public final class SubagentConfig {

    /**
     * 子 Agent 的轮数上限。
     *
     * <p>30 和教材一致。为什么要有上限：{@code task} 是<b>同步</b>调用，
     * 父 Agent 在等它。子 Agent 一直调工具不收尾的话，父 Agent 就一直卡着，
     * 而父 Agent 自己的轮数上限在这期间<b>一轮都没走</b> —— 一次委派就能
     * 把整个请求拖到超时。</p>
     */
    public static final int MAX_SUBAGENT_ROUNDS = 30;

    /**
     * 子 Agent 的固定职责提示。
     *
     * <p>三句话，每句都在关掉一种失控：「只做这一件事」防止它顺手改别的；
     * 「给出有证据的结论」防止它回一句「我看过了，没问题」；
     * 「不要再委派」是递归委派的第一道防线（第二道是注册表里根本没有
     * {@code task}，见 {@link SubagentTool}）。</p>
     */
    public static final String DEFAULT_SYSTEM_PROMPT =
            "你是一个专注的子 Agent，在当前工作区里只完成被委派的这一件任务。"
                    + "完成后给出简洁、有文件或命令证据的结论。"
                    + "不要再把任务继续委派给别人。";

    /** 默认的子 Agent 模型名；和阶段 8 的测试用名保持一致。 */
    public static final String DEFAULT_MODEL = "deepseek-v4-flash";

    private final ModelClientFactory modelFactory;
    private final ToolRegistryFactory toolsFactory;
    private final HookRegistry hooks;
    private final PermissionPolicy policy;
    private final String systemPrompt;
    private final int maxRounds;
    private final long toolTimeoutMillis;
    private final String model;
    private final TraceIdGenerator traceIdGenerator;

    /**
     * @param modelFactory      模型工厂，不能为 null
     * @param toolsFactory      工具注册表工厂，不能为 null
     * @param hooks             与父 Agent 共享的 Hook；<b>不能为 null</b>，没有 Hook 请传空注册表
     * @param policy            与父 Agent 共享的权限策略；<b>不能为 null</b>，
     *                          没有自定义规则请传 {@code new PermissionPolicy()}
     * @param systemPrompt      子 Agent 的职责提示；null 表示用默认值，但不允许空白
     * @param maxRounds         轮数上限；只允许收紧，不允许超过 {@link #MAX_SUBAGENT_ROUNDS}
     * @param toolTimeoutMillis 子 Agent 的单个工具超时
     * @param model             子 Agent 用的模型名；null 表示用 {@link #DEFAULT_MODEL}
     * @param traceIdGenerator  子 Agent 的 trace id 来源；null 表示用随机 UUID
     */
    public SubagentConfig(ModelClientFactory modelFactory,
                          ToolRegistryFactory toolsFactory,
                          HookRegistry hooks,
                          PermissionPolicy policy,
                          String systemPrompt,
                          int maxRounds,
                          long toolTimeoutMillis,
                          String model,
                          TraceIdGenerator traceIdGenerator) {
        if (modelFactory == null) {
            throw new IllegalArgumentException("modelFactory 不能为 null");
        }
        if (toolsFactory == null) {
            throw new IllegalArgumentException("toolsFactory 不能为 null");
        }
        // hooks 传 null 不是「省略配置」，而是一句错话：「子 Agent 不受 Hook 管」。
        // 没有 Hook 时传空注册表 —— 受管但当前无规则，和不受管是两件事。
        if (hooks == null) {
            throw new IllegalArgumentException(
                    "hooks 不能为 null；父 Agent 没有 Hook 时请传空的 HookRegistry，"
                            + "子 Agent 不存在「不受 Hook 管」这个状态");
        }
        // policy 同理，而且后果比 hooks 更重：null 会让循环整段跳过裁决，
        // DESTRUCTIVE 默认 ask 和受保护设备硬边界都不再求值。
        // 空的 PermissionPolicy 才是「受管但没有自定义规则」的正确表达。
        if (policy == null) {
            throw new IllegalArgumentException(
                    "policy 不能为 null；没有自定义规则时请传 new PermissionPolicy()，"
                            + "那仍会执行 DESTRUCTIVE 默认确认和硬边界。"
                            + "传 null 会让子 Agent 完全没有裁决 —— 那正是 task 变成提权路径的方式");
        }
        String effectiveModel = model == null ? DEFAULT_MODEL : model;
        if (effectiveModel.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能是空白；不传请用 null 表示取默认值");
        }
        // null 用默认值，但空白字符串是<b>写错了</b>，不能静默当成默认。
        // 一个空的职责提示会让子 Agent 完全失去边界约束。
        String effectivePrompt = systemPrompt == null ? DEFAULT_SYSTEM_PROMPT : systemPrompt;
        if (effectivePrompt.trim().isEmpty()) {
            throw new IllegalArgumentException("systemPrompt 不能是空白；不传请用 null 表示取默认值");
        }
        if (maxRounds <= 0) {
            throw new IllegalArgumentException("maxRounds 必须为正数");
        }
        // 只允许收紧不允许放宽：调用方能把上限调到 100 的话，
        // 「同步委派最多拖多久」这件事就没有上界了。
        if (maxRounds > MAX_SUBAGENT_ROUNDS) {
            throw new IllegalArgumentException(
                    "maxRounds 最多 " + MAX_SUBAGENT_ROUNDS + "，当前 " + maxRounds
                            + "；这个上限只能收紧，不能放宽");
        }
        if (toolTimeoutMillis <= 0) {
            throw new IllegalArgumentException("toolTimeoutMillis 必须为正数");
        }
        this.modelFactory = modelFactory;
        this.toolsFactory = toolsFactory;
        this.hooks = hooks;
        this.policy = policy;
        this.systemPrompt = effectivePrompt;
        this.maxRounds = maxRounds;
        this.toolTimeoutMillis = toolTimeoutMillis;
        this.model = effectiveModel;
        this.traceIdGenerator =
                traceIdGenerator == null ? TraceIdGenerator.RANDOM : traceIdGenerator;
    }

    /** 用默认职责提示、默认上限、默认模型名的简化构造。 */
    public SubagentConfig(ModelClientFactory modelFactory,
                          ToolRegistryFactory toolsFactory,
                          HookRegistry hooks,
                          PermissionPolicy policy) {
        this(modelFactory, toolsFactory, hooks, policy,
                null, MAX_SUBAGENT_ROUNDS, 2000L, null, null);
    }

    /** 指定职责提示、轮数和超时，模型名与 trace id 取默认。 */
    public SubagentConfig(ModelClientFactory modelFactory,
                          ToolRegistryFactory toolsFactory,
                          HookRegistry hooks,
                          PermissionPolicy policy,
                          String systemPrompt,
                          int maxRounds,
                          long toolTimeoutMillis) {
        this(modelFactory, toolsFactory, hooks, policy,
                systemPrompt, maxRounds, toolTimeoutMillis, null, null);
    }

    public ModelClientFactory getModelFactory() {
        return modelFactory;
    }

    public ToolRegistryFactory getToolsFactory() {
        return toolsFactory;
    }

    /** @return 与父 Agent 共享的 Hook；构造期已保证非 null */
    public HookRegistry getHooks() {
        return hooks;
    }

    /** @return 共享的权限策略；保证非 null */
    public PermissionPolicy getPolicy() {
        return policy;
    }

    public String getSystemPrompt() {
        return systemPrompt;
    }

    public int getMaxRounds() {
        return maxRounds;
    }

    public long getToolTimeoutMillis() {
        return toolTimeoutMillis;
    }

    /** @return 子 Agent 用的模型名，非空 */
    public String getModel() {
        return model;
    }

    /** @return 子 Agent 的 trace id 来源，非 null */
    public TraceIdGenerator getTraceIdGenerator() {
        return traceIdGenerator;
    }
}
