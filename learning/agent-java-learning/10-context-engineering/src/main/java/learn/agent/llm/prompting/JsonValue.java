package learn.agent.llm.prompting;

import java.util.List;
import java.util.Map;

/**
 * JSON 值类型标记接口。
 * 只允许可稳定序列化的值：null、布尔、数字、字符串、数组、对象。
 * 拒绝函数、Date、NaN、Infinity、循环引用、Symbol 等不可序列化的值。
 */
public interface JsonValue {

    /**
     * 转换为稳定的 JSON 字符串（键排序）。
     */
    String toStableJson();

    // 工厂方法
    static JsonNull ofNull() {
        return JsonNull.INSTANCE;
    }

    static JsonBoolean of(boolean value) {
        return JsonBoolean.of(value);
    }

    static JsonNumber of(double value) {
        if (!Double.isFinite(value)) {
            throw new PromptContextException("context contains a non-finite JSON number");
        }
        return new JsonNumber(value);
    }

    static JsonString of(String value) {
        if (value == null) {
            throw new IllegalArgumentException("String value cannot be null (use JsonNull instead)");
        }
        return new JsonString(value);
    }

    static JsonArray of(List<JsonValue> items) {
        return new JsonArray(items);
    }

    static JsonObject of(Map<String, JsonValue> properties) {
        return new JsonObject(properties);
    }
}
