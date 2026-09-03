package learn.agent.llm.prompting;

/**
 * JSON 布尔值（两个单例）。
 */
public final class JsonBoolean implements JsonValue {

    public static final JsonBoolean TRUE = new JsonBoolean(true);
    public static final JsonBoolean FALSE = new JsonBoolean(false);

    private final boolean value;

    private JsonBoolean(boolean value) {
        this.value = value;
    }

    public static JsonBoolean of(boolean value) {
        return value ? TRUE : FALSE;
    }

    public boolean value() {
        return value;
    }

    @Override
    public String toStableJson() {
        return Boolean.toString(value);
    }

    @Override
    public String toString() {
        return Boolean.toString(value);
    }

    @Override
    public boolean equals(Object obj) {
        if (!(obj instanceof JsonBoolean)) {
            return false;
        }
        JsonBoolean other = (JsonBoolean) obj;
        return value == other.value;
    }

    @Override
    public int hashCode() {
        return Boolean.hashCode(value);
    }
}
