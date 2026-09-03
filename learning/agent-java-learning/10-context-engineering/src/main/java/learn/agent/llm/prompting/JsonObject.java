package learn.agent.llm.prompting;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.stream.Collectors;

/**
 * JSON 对象值（不可变，键按字母顺序存储以确保稳定序列化）。
 */
public final class JsonObject implements JsonValue {

    private final Map<String, JsonValue> properties;

    public JsonObject(Map<String, JsonValue> properties) {
        if (properties == null) {
            throw new IllegalArgumentException("properties cannot be null");
        }
        // 按键排序存储，确保稳定序列化
        this.properties = Collections.unmodifiableMap(new TreeMap<>(properties));
    }

    /**
     * 工厂方法，从 Map 创建 JsonObject。
     */
    public static JsonObject of(Map<String, JsonValue> properties) {
        return new JsonObject(properties);
    }

    /**
     * 创建一个空的 JsonObject。
     */
    public static JsonObject empty() {
        return new JsonObject(Collections.emptyMap());
    }

    public Map<String, JsonValue> properties() {
        return properties;
    }

    public JsonValue get(String key) {
        return properties.get(key);
    }

    public boolean containsKey(String key) {
        return properties.containsKey(key);
    }

    public int size() {
        return properties.size();
    }

    public boolean isEmpty() {
        return properties.isEmpty();
    }

    @Override
    public String toStableJson() {
        return properties.entrySet().stream()
                .map(entry -> JsonValue.of(entry.getKey()).toStableJson() + ":" + entry.getValue().toStableJson())
                .collect(Collectors.joining(",", "{", "}"));
    }

    @Override
    public String toString() {
        return toStableJson();
    }

    @Override
    public boolean equals(Object obj) {
        if (!(obj instanceof JsonObject)) {
            return false;
        }
        JsonObject other = (JsonObject) obj;
        return properties.equals(other.properties);
    }

    @Override
    public int hashCode() {
        return Objects.hash(properties);
    }
}
