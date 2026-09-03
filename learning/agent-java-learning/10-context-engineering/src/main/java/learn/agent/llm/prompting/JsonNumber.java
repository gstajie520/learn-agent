package learn.agent.llm.prompting;

import java.util.Objects;

/**
 * JSON 数字值（仅接受有限数）。
 */
public final class JsonNumber implements JsonValue {

    private final double value;

    public JsonNumber(double value) {
        if (!Double.isFinite(value)) {
            throw new PromptContextException("context contains a non-finite JSON number");
        }
        this.value = value;
    }

    public double value() {
        return value;
    }

    @Override
    public String toStableJson() {
        // 如果是整数，输出不带小数点
        if (value == Math.floor(value) && !Double.isInfinite(value)) {
            return Long.toString((long) value);
        }
        return Double.toString(value);
    }

    @Override
    public String toString() {
        return toStableJson();
    }

    @Override
    public boolean equals(Object obj) {
        if (!(obj instanceof JsonNumber)) {
            return false;
        }
        JsonNumber other = (JsonNumber) obj;
        return Double.compare(value, other.value) == 0;
    }

    @Override
    public int hashCode() {
        return Objects.hash(value);
    }
}
