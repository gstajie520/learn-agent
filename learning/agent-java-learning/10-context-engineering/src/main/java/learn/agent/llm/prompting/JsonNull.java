package learn.agent.llm.prompting;

/**
 * JSON null 值（单例）。
 */
public final class JsonNull implements JsonValue {

    public static final JsonNull INSTANCE = new JsonNull();

    private JsonNull() {
    }

    @Override
    public String toStableJson() {
        return "null";
    }

    @Override
    public String toString() {
        return "null";
    }

    @Override
    public boolean equals(Object obj) {
        return obj instanceof JsonNull;
    }

    @Override
    public int hashCode() {
        return 0;
    }
}
