package learn.agent.llm.plan;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.ModelClient;
import learn.agent.llm.hook.HookedAgentLoop;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.structured.ValidationResult;
import learn.agent.llm.tool.ToolArgumentValidator;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;

/**
 * {@code task} 工具：把一个自包含的子任务交给一个隔离的子 Agent。
 *
 * <h3>这一课解决什么</h3>
 * <p>第 1 课让主 Agent 记住自己要干什么，但它没有减少<b>探索过程本身</b>带来的
 * 上下文。让一个 Agent 去追一个深调用链里的 bug：它读文件、搜符号、跑命令，
 * 几十轮工具结果很快就把历史塞满。计划还在，可主 Agent 现在要同时记住
 * 最初目标、当前计划，<b>以及一大段和最终结论无关的探索轨迹</b>。</p>
 *
 * <p>子 Agent 的思路是：这段探索根本不该进主对话。派一个从零开始的子 Agent
 * 去查，主 Agent 只接收<b>一句有证据的结论</b>。中间那三十轮读文件记录，
 * 留在子 Agent 的边界里，随它一起消失。</p>
 *
 * <pre>{@code
 * 父 Agent
 *   assistant: task(description="查清本项目用的测试框架")
 *         │
 *         ▼
 *   子 Agent（全新历史）
 *     system: 只做这一件事，给出有证据的结论，不要再委派
 *     user:   查清本项目用的测试框架
 *     ...三十轮读文件、搜索、跑命令...
 *         │
 *         ▼
 * 父 Agent
 *   tool: "JUnit 5。证据：pom.xml 里 junit-jupiter 5.8.2"   ← 只有这一句
 * }</pre>
 *
 * <h3>隔离的<b>只有</b>消息历史</h3>
 * <p>这是本课最容易误读的地方。父子共享同一个 JVM、同一个 {@link ToolContext}
 * （同一身份、同一场景）、同一组 Hook、同一份权限策略；子 Agent 写下的副作用
 * <b>会保留</b>。它<b>不是沙箱</b>，也不会自动获得更少或更多权限。
 * 详见 {@link SubagentConfig} 的说明。</p>
 *
 * <h3>递归委派的两道防线</h3>
 * <ol>
 *   <li><b>提示词</b>：职责提示里写明「不要再委派」。这是软约束 ——
 *       模型可以不听。</li>
 *   <li><b>注册表</b>：子 Agent 的注册表里<b>根本没有</b> {@code task}。
 *       它想调也调不到，只会拿到一条 {@code tool_not_found}。</li>
 * </ol>
 * <p>为什么两道都要：只靠提示词，遇到提示词注入就失效；只靠注册表，
 * 模型会反复尝试委派、浪费轮数。前者省 token，后者兜底 ——
 * <b>而兜底那道才是真正生效的那道。</b></p>
 *
 * <p>本类在 {@link #runTask} 里显式检查工厂产出的注册表<b>有没有</b>
 * {@code task}，有就直接报配置错误。这道检查针对的不是模型，是<b>写代码的人</b>：
 * 一个图省事的 {@code toolsFactory} 直接返回父 Agent 的注册表，递归委派就复活了。</p>
 */
public final class SubagentTool {

    /** 工具名。 */
    public static final String TOOL_NAME = "task";

    private final SubagentConfig config;

    private final ToolDefinition toolDefinition;

    /**
     * @param config 一次委派需要的全部配置，不能为 null
     */
    public SubagentTool(SubagentConfig config) {
        if (config == null) {
            throw new IllegalArgumentException("config 不能为 null");
        }
        this.config = config;
        this.toolDefinition = new ToolDefinition(
                TOOL_NAME,
                "把一个自包含的子任务交给独立的子 Agent 执行，只返回它的最终结论。"
                        + "适合需要多轮探索、但中间过程对当前对话没有价值的任务。",
                buildParametersSchema(),
                // Java 的 ToolEffect 没有教材那个 external，域重映射成 WRITE：
                // 子 Agent 能写文件，所以不是 READ；标成 DESTRUCTIVE 会让<b>每一次</b>
                // 委派都弹确认框，这个机制就没人用了。真正的破坏性操作由子 Agent
                // 自己注册表里那些工具的等级决定 —— 权限策略是共享的，拦得住。
                ToolEffect.WRITE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return runTask(arguments, context);
                    }
                },
                new DescriptionValidator());
    }

    /** @return 注册进父 Agent 的 {@code ToolRegistry} 的工具定义 */
    public ToolDefinition getToolDefinition() {
        return toolDefinition;
    }

    /**
     * 跑一次委派。
     *
     * <p>这个方法是一道<b>边界</b>：里面无论出什么问题，回给父模型的都必须是一条
     * 结构化的工具错误，不能是异常，也不能是内部异常文本 —— 那种文本会把子 Agent
     * 的实现细节、甚至文件路径泄漏进父对话。</p>
     */
    private ToolExecutionResult runTask(JsonNode arguments, ToolContext context) {
        String description = arguments.get("description").asText().trim();

        HookedAgentLoop childLoop = null;
        try {
            // 1) 工具注册表：每次新建。共享会让上一个子任务的注册内容泄漏过来。
            ToolRegistry childTools = config.getToolsFactory().create();
            if (childTools == null) {
                return ToolExecutionResult.error("subagent_configuration_error",
                        "子 Agent 的工具注册表工厂返回了 null");
            }
            // 递归委派的第二道防线，针对的是写错 factory 的人（见类注释）。
            if (childTools.names().contains(TOOL_NAME)) {
                return ToolExecutionResult.error("subagent_configuration_error",
                        "子 Agent 的注册表里不能包含 " + TOOL_NAME + " —— 那会打开无边界的递归委派");
            }

            // 2) 模型客户端：每次新建。共享会让两次委派读同一个响应队列。
            ModelClient childModel = config.getModelFactory().create();
            if (childModel == null) {
                return ToolExecutionResult.error("subagent_configuration_error",
                        "子 Agent 的模型工厂返回了 null");
            }

            // 3) 新循环 = 全新历史。父 Agent 的消息一条都不传进来。
            //    但 Hook、权限、ToolContext 照原样共享 —— 治理边界不能被绕过。
            childLoop = new HookedAgentLoop(config.getModel(), childModel, childTools, context,
                    config.getMaxRounds(), config.getToolTimeoutMillis(),
                    config.getTraceIdGenerator(), config.getPolicy(), config.getHooks());

            GuardedTrace trace = childLoop.run(config.getSystemPrompt(), description);
            return toToolResult(trace);
        } catch (RuntimeException e) {
            // 刻意不把 e.getMessage() 放进结果：父模型不需要知道子 Agent 内部
            // 哪一行抛的异常，而那段文本可能带路径、参数或身份信息。
            return ToolExecutionResult.error("subagent_execution_error", "子 Agent 执行失败");
        } finally {
            // Java 特有的一笔：HookedAgentLoop 内部有 ToolTimeoutGuard，
            // 它持有一个线程池。不关的话，<b>每次委派泄漏一个线程池</b> ——
            // 教材是 Node 单线程模型，没有这个问题，照抄会漏掉这一句。
            if (childLoop != null) {
                childLoop.shutdown();
            }
        }
    }

    /**
     * 把子 Agent 的轨迹翻译成一条工具结果。
     *
     * <p>只有 {@link StopReason#FINAL_ANSWER} 才算成功。其余全部归成错误，
     * 而且<b>不回传子 Agent 最后那条工具结果</b> —— 轮数耗尽时最后一条工具结果
     * 通常看着像个正常答案，把它当结论回传，父 Agent 会以为子任务成功了。</p>
     */
    private ToolExecutionResult toToolResult(GuardedTrace trace) {
        StopReason reason = trace.getStopReason();
        if (reason == StopReason.FINAL_ANSWER) {
            return ToolExecutionResult.success(trace.getFinalAnswer());
        }
        if (reason == StopReason.MAX_ROUNDS) {
            return ToolExecutionResult.error("subagent_turn_limit",
                    "子 Agent 用满了 " + config.getMaxRounds() + " 轮仍未给出结论");
        }
        // 截断、模型报错、协议违约：都归成一条边界错误。
        // 父 Agent 需要知道「委派失败了」，不需要知道子 Agent 内部怎么失败的。
        return ToolExecutionResult.error("subagent_execution_error",
                "子 Agent 未能完成任务（停止原因：" + reason.getWireValue() + "）");
    }

    /** {@code task} 的参数 Schema。只有一个字段，刻意不给别的。 */
    private static String buildParametersSchema() {
        return "{"
                + "\"type\":\"object\","
                + "\"properties\":{"
                + "\"description\":{"
                + "\"type\":\"string\","
                + "\"description\":\"一个自包含的任务描述。子 Agent 看不到当前对话，"
                + "所以必须把背景、目标和判定标准都写进这一句话里。\""
                + "}"
                + "},"
                + "\"required\":[\"description\"]"
                + "}";
    }

    /**
     * {@code description} 的校验器。
     *
     * <p>只校验一件事：非空。<b>但这个「非空」很重要</b> —— 子 Agent 看不到父
     * 对话，一个空描述或者「继续」这种描述，它完全无从下手，三十轮全都是浪费。</p>
     */
    private static final class DescriptionValidator implements ToolArgumentValidator {

        @Override
        public ValidationResult<JsonNode> validate(JsonNode arguments) {
            if (arguments == null) {
                return ValidationResult.fail("参数不能为 null");
            }
            JsonNode description = arguments.get("description");
            if (description == null || !description.isTextual()) {
                return ValidationResult.fail("缺少 description 字段（字符串）");
            }
            if (description.asText().trim().isEmpty()) {
                return ValidationResult.fail(
                        "description 不能为空；子 Agent 看不到当前对话，"
                                + "必须把背景和目标写进描述里");
            }
            return ValidationResult.ok(arguments);
        }
    }
}
