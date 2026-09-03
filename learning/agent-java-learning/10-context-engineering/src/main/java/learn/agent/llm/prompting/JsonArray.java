package learn.agent.llm.prompting;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * JSON 数组值（不可变）。
 */
public final class JsonArray implements JsonValue {

    private final List<JsonValue> items;

    public JsonArray(List<JsonValue> items) {
        if (items == null) {
            throw new IllegalArgumentException("items cannot be null");
        }
        this.items = Collections.unmodifiableList(new ArrayList<>(items));
    }

    public List<JsonValue> items() {
        return items;
    }

    public int size() {
        return items.size();
    }

    public JsonValue get(int index) {
        return items.get(index);
    }

    @Override
    public String toStableJson() {
        return items.stream()
                .map(JsonValue::toStableJson)
                .collect(Collectors.joining(",", "[", "]"));
    }

    @Override
    public String toString() {
        return toStableJson();
    }

    @Override
    public boolean equals(Object obj) {
        if (!(obj instanceof JsonArray)) {
            return false;
        }
        JsonArray other = (JsonArray) obj;
        return items.equals(other.items);
    }

    @Override
    public int hashCode() {
        return Objects.hash(items);
    }
}
