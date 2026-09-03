package learn.agent.llm.memory;

/**
 * 记忆记录：不可变值对象。
 */
public class MemoryRecord {
    private final String name;
    private final String description;
    private final MemoryType kind;
    private final String body;

    public MemoryRecord(String name, String description, MemoryType kind, String body) {
        if (name == null || name.isEmpty()) {
            throw new IllegalArgumentException("name must not be empty");
        }
        if (description == null || description.isEmpty()) {
            throw new IllegalArgumentException("description must not be empty");
        }
        if (kind == null) {
            throw new IllegalArgumentException("kind must not be null");
        }
        if (body == null || body.isEmpty()) {
            throw new IllegalArgumentException("body must not be empty");
        }
        this.name = name;
        this.description = description;
        this.kind = kind;
        this.body = body;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public MemoryType getKind() {
        return kind;
    }

    public String getBody() {
        return body;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof MemoryRecord)) return false;
        MemoryRecord other = (MemoryRecord) obj;
        return name.equals(other.name) &&
               description.equals(other.description) &&
               kind == other.kind &&
               body.equals(other.body);
    }

    @Override
    public int hashCode() {
        int result = name.hashCode();
        result = 31 * result + description.hashCode();
        result = 31 * result + kind.hashCode();
        result = 31 * result + body.hashCode();
        return result;
    }
}
