package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;
import learn.agent.llm.lesson03.ValidationResult;

/**
 * 工具参数的业务校验器。
 *
 * <p>这一层做的事情，是 JSON Schema 做不到的：Schema 只能说「x 必须是整数」，
 * 说不了「x 必须落在当前场景的边界内」。所以每个工具可以带一个自己的校验器，
 * 在<b>执行之前</b>把参数拦下来。
 *
 * <p>为什么复用第 3 课的 {@link ValidationResult}：那一课已经确立了
 * 「校验失败要一次性返回全部错误，而不是抛第一个异常就跑」的约定。
 * 工具参数校验是同一类问题，没有理由换一套返回类型。
 *
 * <p>注意签名里没有 {@code throws}，也没有 {@link ToolContext}。
 * 没有 context 是故意的：这一层只判断「参数本身合不合法」，
 * 不去碰任何外部状态，因此天然没有副作用。
 */
public interface ToolArgumentValidator {

    /**
     * 校验模型给出的参数。
     *
     * @param arguments 已经解析成 JSON 对象的参数（保证非 null、保证是 object）
     * @return 校验通过时 {@code ok(arguments)}；失败时 {@code fail(错误列表)}
     */
    ValidationResult<JsonNode> validate(JsonNode arguments);
}
