package learn.agent.llm.plan;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.structured.ValidationResult;
import learn.agent.llm.tool.ToolArgumentValidator;

/**
 * {@code todo_write} 的参数校验器。
 *
 * <p>复用第 4 课的 {@link ToolArgumentValidator} 接口和第 3 课的
 * {@link ValidationResult}：一次性收集全部错误，不抛第一个异常就跑。
 * 模型一次写错三项，最好一次全告诉它，否则要来回三轮才能改对，
 * 每一轮都是真金白银的 token。</p>
 *
 * <h3>这一层只做纯函数判断</h3>
 * <p>和第 3 课确立的分层一致：这里只看「参数本身合不合法」（是不是数组、
 * 内容空不空、状态字面值认不认识、条数超不超上限），<b>不看任何外部状态</b>。
 * 它不需要知道当前计划是什么 —— 完整快照的语义就是「不管之前是什么，
 * 现在就是这张表」，所以这一层天然没有「与旧状态是否兼容」的问题。</p>
 *
 * <h3>为什么坚持完整快照</h3>
 * <p>增量补丁（{@code todo_update(3, "completed")}）在短对话里没问题，
 * 在长对话里必然漂移：模型记不清第 3 项是什么了，它只是在猜一个下标。
 * 要求完整快照的代价是每次多花一些 token，收益是<b>模型每次都必须把
 * 整个计划重读一遍</b> —— 这个「重读」本身就是对抗遗忘的机制。</p>
 */
public final class TodoWriteValidator implements ToolArgumentValidator {

    /** 一次快照最多多少项。防止模型一次塞进一个超大数组把上下文顶爆。 */
    public static final int MAX_TODOS = 50;

    /** 单项描述的最大长度。同样是上下文预算的保护。 */
    public static final int MAX_CONTENT_LENGTH = 200;

    /** 顶层允许出现的字段名。对应教材外层 schema 的 {@code .strict()}。 */
    private static final Set<String> KNOWN_TOP_FIELDS =
            Collections.unmodifiableSet(new LinkedHashSet<String>(Arrays.asList("todos")));

    /** 单项允许出现的字段名。对应教材内层 schema 的 {@code .strict()}。 */
    private static final Set<String> KNOWN_ITEM_FIELDS = Collections.unmodifiableSet(
            new LinkedHashSet<String>(Arrays.asList("content", "status")));

    @Override
    public ValidationResult<JsonNode> validate(JsonNode arguments) {
        // 校验器是防线，防线自己不该崩 —— 第 3 课的教训，null 返回 fail 不抛异常。
        if (arguments == null) {
            return ValidationResult.fail("参数不能为 null");
        }

        List<String> errors = new ArrayList<String>();

        // 顶层只允许 todos 一个字段。教材两层 schema 都用 Zod 的 .strict()，
        // 这里是它的等价物。
        //
        // 为什么「多几个字段无所谓」是错的：writeTodos 只读 content 和 status，
        // 多出来的字段会被<b>静默丢掉</b>。而工具结果回传整张 JSON 的全部理由，
        // 就是让模型逐字段对比、自己发现差异 —— 静默丢字段恰好制造出一次
        // 「有差异但没有任何解释」的不一致，模型只能猜是不是有人动过它的计划。
        // 拒绝未知字段是把这种情况变成一条明确的、可改的错误。
        rejectUnknownFields(arguments, KNOWN_TOP_FIELDS, "顶层出现未知字段", errors);

        JsonNode todos = arguments.get("todos");
        if (todos == null) {
            // 缺字段就没法继续逐项检查了。但已经收集到的未知字段错误要一起报出去 ——
            // 「缺 todos」和「多了个 todo」往往是同一个笔误的两面，只报一半
            // 模型下一轮会改错方向。
            errors.add("缺少 todos 字段；todo_write 需要完整的任务快照");
            return ValidationResult.fail(errors);
        }
        if (!todos.isArray()) {
            errors.add("todos 必须是数组，实际是：" + todos.getNodeType()
                    + "；todo_write 只接受完整快照，不接受单项补丁");
            return ValidationResult.fail(errors);
        }
        if (todos.size() > MAX_TODOS) {
            errors.add("todos 最多 " + MAX_TODOS + " 项，当前 " + todos.size() + " 项");
        }

        // 允许空数组：清空计划是合法操作（任务全部做完后收尾）。
        for (int i = 0; i < todos.size(); i++) {
            // 下标从 1 开始报给模型：模型看到的是它自己写的那个列表，从 1 数更自然。
            validateItem(todos.get(i), i + 1, errors);
        }

        if (!errors.isEmpty()) {
            return ValidationResult.fail(errors);
        }
        return ValidationResult.ok(arguments);
    }

    /** 校验单项，把错误追加进 errors 而不是立刻返回 —— 为的是一次收集全部问题。 */
    private void validateItem(JsonNode item, int position, List<String> errors) {
        if (item == null || !item.isObject()) {
            errors.add("第 " + position + " 项必须是对象，含 content 和 status 两个字段");
            return;
        }

        JsonNode content = item.get("content");
        if (content == null || !content.isTextual()) {
            errors.add("第 " + position + " 项缺少 content 字段（字符串）");
        } else if (content.asText().trim().isEmpty()) {
            // 先 trim 再判空：只有空格的描述等于没有描述，但 JSON 层面它是合法字符串。
            errors.add("第 " + position + " 项的 content 不能是空白");
        } else if (content.asText().trim().length() > MAX_CONTENT_LENGTH) {
            errors.add("第 " + position + " 项的 content 超过 " + MAX_CONTENT_LENGTH
                    + " 字符；任务描述应该是一句话，不是一段方案");
        }

        JsonNode status = item.get("status");
        if (status == null || !status.isTextual()) {
            errors.add("第 " + position + " 项缺少 status 字段；合法值：" + TodoStatus.describeAll());
        } else if (TodoStatus.fromWireValue(status.asText()) == null) {
            // 把合法值列出来，模型下一轮才改得对。只说「非法」等于让它继续猜。
            errors.add("第 " + position + " 项的 status 非法：" + status.asText()
                    + "；合法值：" + TodoStatus.describeAll());
        }

        // 单项也拒绝未知字段，理由和顶层那道一样，但后果更直接：
        // writeTodos 只读 content 和 status，多出来的 priority、id、note
        // 会被静默丢掉。而回传整张快照的目的正是让模型逐字段对比 ——
        // 丢字段等于制造一次「模型看得见、但没有任何解释」的差异。
        rejectUnknownFields(item, KNOWN_ITEM_FIELDS,
                "第 " + position + " 项出现未知字段", errors);
    }

    /**
     * 把 {@code node} 上不在白名单里的字段名收进 {@code errors}。
     *
     * <p>对应教材两处 Zod {@code .strict()}。做成共用方法而不是写两遍，
     * 是因为「顶层」和「单项」这两道锁将来只可能一起改。</p>
     */
    private static void rejectUnknownFields(JsonNode node,
                                            Set<String> known,
                                            String prefix,
                                            List<String> errors) {
        List<String> unknown = new ArrayList<String>();
        Iterator<String> names = node.fieldNames();
        while (names.hasNext()) {
            String name = names.next();
            if (!known.contains(name)) {
                unknown.add(name);
            }
        }
        if (!unknown.isEmpty()) {
            errors.add(prefix + "：" + unknown + "；只接受 " + known);
        }
    }
}
