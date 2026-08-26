package learn.agent.llm.lesson03;

/**
 * 场景操作的动作类型。
 *
 * <p>每个动作带一个 {@code destructive} 标记，这是本课的一个重点：
 * <b>不是所有操作的风险等级都一样</b>。</p>
 *
 * <p>「在北侧加一台雷达」做错了，删掉重来即可；
 * 「删除所有设备」做错了，用户的工作就没了。
 * 所以危险操作必须走额外的确认流程，而不是和普通操作共用一条代码路径。</p>
 *
 * <p>把这个标记放在枚举上而不是散落在 if 判断里，是为了让「哪些操作危险」
 * 成为一个可以被测试、被审计的<b>单一事实来源</b>。</p>
 */
public enum OperationType {

    /** 新增设备。做错了可以删除，风险低。 */
    CREATE("create", false),

    /** 移动设备位置。做错了可以移回来，风险低。 */
    MOVE("move", false),

    /** 删除单个设备。不可逆，需要确认。 */
    DELETE("delete", true),

    /** 清空场景内所有设备。破坏性最强，必须确认。 */
    CLEAR_ALL("clear_all", true);

    /** JSON 里使用的字面值。 */
    private final String wireValue;

    /** 是否属于破坏性操作。 */
    private final boolean destructive;

    OperationType(String wireValue, boolean destructive) {
        this.wireValue = wireValue;
        this.destructive = destructive;
    }

    public String getWireValue() {
        return wireValue;
    }

    /**
     * 是否是破坏性操作。
     *
     * <p>破坏性操作即使通过了全部格式和业务校验，也<b>只能生成预览</b>，
     * 必须由人确认后才允许真正执行。模型不能自己决定删数据。</p>
     */
    public boolean isDestructive() {
        return destructive;
    }

    /** 按 JSON 字面值查找；不认识时返回 {@code null}。 */
    public static OperationType fromWireValue(String value) {
        if (value == null) {
            return null;
        }
        for (OperationType type : values()) {
            if (type.wireValue.equalsIgnoreCase(value.trim())) {
                return type;
            }
        }
        return null;
    }

    /** 返回全部合法字面值，用于错误信息。 */
    public static String allWireValues() {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < values().length; i++) {
            if (i > 0) {
                builder.append(", ");
            }
            builder.append(values()[i].wireValue);
        }
        return builder.toString();
    }
}
