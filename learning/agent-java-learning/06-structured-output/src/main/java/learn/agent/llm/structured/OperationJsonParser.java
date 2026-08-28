package learn.agent.llm.structured;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * 把模型返回的文本解析成 {@link SceneOperation}。
 *
 * <p>这是「模型输出 → 领域对象」的第一道关口，负责两件事：
 * <b>提取 JSON</b> 和 <b>检查字段类型</b>。至于字段搭配是否合理，
 * 交给 {@link OperationSchemaValidator}；业务上能不能做，
 * 交给 {@link SceneBusinessValidator}。</p>
 *
 * <h2>为什么不能直接 {@code mapper.readValue(text, SceneOperation.class)}</h2>
 *
 * <p>因为模型输出<b>不是</b>干净的 JSON。真实环境里至少三种情况：</p>
 *
 * <ol>
 *   <li><b>包在代码围栏里</b>：模型很爱输出
 *       <code>```json ... ```</code>，即使系统提示说了「不要代码围栏」。
 *       这不是模型不听话 —— 它的训练数据里 JSON 大多带着围栏；</li>
 *   <li><b>前后有解释文字</b>：「好的，这是操作：{...}，希望有帮助！」；</li>
 *   <li><b>被截断</b>：{@code finishReason=LENGTH} 时 JSON 缺右括号。</li>
 * </ol>
 *
 * <p>直接 {@code readValue} 在这三种情况下都抛 Jackson 异常，
 * 而异常信息（{@code Unexpected character '`'}）对排查没有帮助 ——
 * 你看不出是模型多说了话，还是输出被截断。</p>
 *
 * <h2>宽容的边界在哪里</h2>
 *
 * <p>提取 JSON 和大小写不敏感是<b>宽容</b>的：它们适配模型的输出习惯，
 * 不改变语义。</p>
 *
 * <p>但字段语义<b>绝不宽容</b>：不猜字段名、不把字符串 {@code "10"} 转成数字、
 * 不给缺失字段填默认值。前者是适配习惯，后者是替模型掩盖错误 ——
 * 一旦开始自动转换，{@code "十"} 也会被悄悄当成 0。</p>
 */
public class OperationJsonParser {

    private final ObjectMapper mapper = new ObjectMapper();

    /**
     * 解析模型输出。
     *
     * @param modelOutput 模型返回的原始文本
     * @return 成功时携带 {@link SceneOperation}；失败时携带可读错误
     */
    public ValidationResult<SceneOperation> parse(String modelOutput) {
        if (modelOutput == null || modelOutput.trim().isEmpty()) {
            // 模型返回空内容是真实存在的情况，不能当成 NPE 崩掉。
            return ValidationResult.fail("模型没有输出任何内容");
        }

        String json = extractJsonObject(modelOutput);
        if (json == null) {
            return ValidationResult.fail(
                    "模型输出里找不到完整的 JSON 对象（可能只输出了文字说明，或输出被截断）。原文开头："
                            + preview(modelOutput));
        }

        JsonNode root;
        try {
            root = mapper.readTree(json);
        } catch (IOException e) {
            // 只回传「格式不合法」，不回传 Jackson 的内部异常细节 ——
            // 那些对模型没有帮助，还可能暴露实现细节。
            return ValidationResult.fail(
                    "模型输出不是合法 JSON，请检查括号和引号是否配对。原文开头：" + preview(json));
        }

        if (!root.isObject()) {
            // 模型可能返回数组（想一次做多个操作）。
            // 本课约定一次只处理一个操作，批量操作属于后续阶段。
            return ValidationResult.fail(
                    "模型输出必须是 JSON 对象，实际是：" + describeNodeType(root));
        }

        // 收集全部字段问题，一次性报出。
        List<String> errors = new ArrayList<String>();

        OperationType type = readOperationType(root, errors);
        DeviceType deviceType = readDeviceType(root, errors);
        String targetId = readText(root, "targetId", errors);
        Integer x = readInteger(root, "x", errors);
        Integer y = readInteger(root, "y", errors);
        String reason = readText(root, "reason", errors);

        checkUnknownFields(root, errors);

        if (!errors.isEmpty()) {
            return ValidationResult.fail(errors);
        }
        // type 为 null 时上面一定已经记了错误，走不到这里。
        return ValidationResult.ok(new SceneOperation(type, deviceType, targetId, x, y, reason));
    }

    /**
     * 从可能夹带围栏和解释文字的输出里，取出第一个完整 JSON 对象。
     *
     * <p>做法是定位第一个 <code>{</code>，再按括号配对找到对应的 <code>}</code>。
     * 关键细节：必须跳过<b>字符串字面量内部</b>的括号，否则
     * {@code {"reason":"用户说}了什么"}} 这种内容会算错结束位置。</p>
     *
     * <p>为什么不用正则：嵌套括号无法用正则可靠匹配。</p>
     *
     * @return 提取出的 JSON 文本；找不到完整对象时返回 {@code null}
     */
    private String extractJsonObject(String text) {
        int start = text.indexOf('{');
        if (start < 0) {
            return null;
        }

        int depth = 0;
        boolean inString = false;
        boolean escaped = false;

        for (int i = start; i < text.length(); i++) {
            char c = text.charAt(i);

            if (escaped) {
                // 上一个字符是反斜杠，本字符没有特殊含义。
                escaped = false;
                continue;
            }
            if (c == '\\') {
                escaped = true;
                continue;
            }
            if (c == '"') {
                inString = !inString;
                continue;
            }
            if (inString) {
                // 字符串内部的括号不参与配对。
                continue;
            }
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return text.substring(start, i + 1);
                }
            }
        }
        // 括号没闭合，通常意味着输出被 maxOutputTokens 截断了。
        return null;
    }

    /** 读取 operation 字段。 */
    private OperationType readOperationType(JsonNode root, List<String> errors) {
        JsonNode node = root.get("operation");
        if (node == null || node.isNull()) {
            errors.add("缺少必填字段 operation，可选值：" + OperationType.allWireValues());
            return null;
        }
        if (!node.isTextual()) {
            errors.add("operation 必须是字符串");
            return null;
        }
        OperationType parsed = OperationType.fromWireValue(node.asText());
        if (parsed == null) {
            // 幻觉枚举值：模型编了一个看起来合理但系统不支持的动作，
            // 例如 update、remove、add。错误信息里列出合法值，模型下一轮就能改对。
            errors.add("不支持的 operation：" + node.asText()
                    + "，只能是 " + OperationType.allWireValues());
        }
        return parsed;
    }

    /** 读取 deviceType 字段；缺失不在这里报错，由 Schema 层按操作类型判断。 */
    private DeviceType readDeviceType(JsonNode root, List<String> errors) {
        JsonNode node = root.get("deviceType");
        if (node == null || node.isNull()) {
            return null;
        }
        if (!node.isTextual()) {
            errors.add("deviceType 必须是字符串");
            return null;
        }
        DeviceType parsed = DeviceType.fromWireValue(node.asText());
        if (parsed == null) {
            errors.add("不支持的 deviceType：" + node.asText()
                    + "，只能是 " + DeviceType.allWireValues());
        }
        return parsed;
    }

    /** 读取可选文本字段；空白视为未提供。 */
    private String readText(JsonNode root, String field, List<String> errors) {
        JsonNode node = root.get(field);
        if (node == null || node.isNull()) {
            return null;
        }
        if (!node.isTextual()) {
            errors.add(field + " 必须是字符串");
            return null;
        }
        String value = node.asText().trim();
        // 空字符串等同于没给。模型返回 "targetId": "" 是真实存在的情况，
        // 用 != null 判断会放行，导致空 id 进入下游查询。
        return value.isEmpty() ? null : value;
    }

    /**
     * 读取整数坐标字段。
     *
     * <p><b>刻意不接受字符串</b>：模型经常输出 {@code "x": "30"}。
     * 自动转换看起来贴心，但一旦开始转换，{@code "三十"} 也会被当成 0，
     * 而且错误会在很深的下游才暴露。</p>
     */
    private Integer readInteger(JsonNode root, String field, List<String> errors) {
        JsonNode node = root.get(field);
        if (node == null || node.isNull()) {
            return null;
        }
        if (!node.isNumber()) {
            errors.add(field + " 必须是数字，不能是字符串。当前值：" + node.asText());
            return null;
        }
        if (!node.canConvertToInt()) {
            errors.add(field + " 必须是整数坐标，当前值：" + node.asText());
            return null;
        }
        double raw = node.asDouble();
        if (raw != Math.floor(raw)) {
            errors.add(field + " 必须是整数坐标，不能有小数部分。当前值：" + node.asText());
            return null;
        }
        return Integer.valueOf(node.asInt());
    }

    /**
     * 检查模型有没有输出契约之外的字段。
     *
     * <p>多余字段本身通常无害，但它是一个<b>信号</b>：说明模型对任务的理解
     * 和契约不一致。比如它输出 {@code "rotation": 90}，意味着它认为可以设置朝向，
     * 而系统并不支持。放过去的话，用户会觉得「我明明说了转 90 度」，
     * 系统却默默忽略了 —— 这种「静默不生效」比报错难查得多。</p>
     */
    private void checkUnknownFields(JsonNode root, List<String> errors) {
        Iterator<String> names = root.fieldNames();
        List<String> unknown = new ArrayList<String>();
        while (names.hasNext()) {
            String name = names.next();
            if (!isKnownField(name)) {
                unknown.add(name);
            }
        }
        if (!unknown.isEmpty()) {
            errors.add("出现了不支持的字段 " + unknown
                    + "，请只输出：operation, deviceType, targetId, x, y, reason");
        }
    }

    private boolean isKnownField(String name) {
        return "operation".equals(name)
                || "deviceType".equals(name)
                || "targetId".equals(name)
                || "x".equals(name)
                || "y".equals(name)
                || "reason".equals(name);
    }

    /** 截取一小段原文用于错误信息；太长会污染日志。 */
    private String preview(String text) {
        String trimmed = text.trim();
        int limit = 80;
        return trimmed.length() <= limit ? trimmed : trimmed.substring(0, limit) + "…（后续省略）";
    }

    /** 描述节点实际类型，让错误信息说清「模型给的是什么」。 */
    private String describeNodeType(JsonNode node) {
        if (node == null || node.isNull()) {
            return "null";
        }
        if (node.isArray()) {
            return "数组（本课一次只支持一个操作）";
        }
        if (node.isTextual()) {
            return "字符串";
        }
        if (node.isNumber()) {
            return "数字";
        }
        if (node.isBoolean()) {
            return "布尔值";
        }
        return node.getNodeType().toString();
    }
}
