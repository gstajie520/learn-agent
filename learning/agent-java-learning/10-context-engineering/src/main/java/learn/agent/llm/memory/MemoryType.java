package learn.agent.llm.memory;

/**
 * 记忆类型枚举。
 */
public enum MemoryType {
    USER("user"),
    FEEDBACK("feedback"),
    PROJECT("project"),
    REFERENCE("reference");

    private final String value;

    MemoryType(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static MemoryType fromValue(String value) {
        for (MemoryType type : values()) {
            if (type.value.equals(value)) {
                return type;
            }
        }
        throw new IllegalArgumentException("Unknown memory type: " + value);
    }
}
