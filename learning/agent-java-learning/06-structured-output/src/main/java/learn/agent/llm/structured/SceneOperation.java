package learn.agent.llm.structured;

/**
 * 一个已经通过校验的场景操作。
 *
 * <p>这个类是本课的<b>核心产物</b>：自然语言「在北侧生成一台雷达」最终要变成
 * 这样一个强类型对象，而不是一段 JSON 字符串或一个 {@code Map}。</p>
 *
 * <p>为什么值得单独建一个类：</p>
 * <ul>
 *   <li><b>类型安全</b>：{@code deviceType} 是枚举，不可能是 "热成像雷达_v2"；</li>
 *   <li><b>不可变</b>：校验通过之后不允许再改，否则校验就白做了 ——
 *       这是最容易被忽略的一点，见下面的说明；</li>
 *   <li><b>业务语义清晰</b>：下游代码读 {@code getDeviceType()} 而不是
 *       {@code map.get("device_type")}，拼错字段名会在编译期报错。</li>
 * </ul>
 *
 * <p><b>关于不可变的重要性：</b>如果这个对象可以被修改，那么「校验通过」
 * 这个结论只在创建那一瞬间成立。之后任何代码都可能把 x 改成越界值，
 * 而下游会因为「这个对象是校验过的」而信任它。不可变让校验结论永久有效。</p>
 *
 * <p>注意本类<b>只做基本的非空检查</b>，不做业务规则校验（坐标范围、
 * 设备是否存在等）。那些属于 {@link SceneOperationValidator} 的职责。
 * 一个类只负责一件事：这个类负责「持有一个合法操作」，
 * 校验器负责「判断什么是合法」。</p>
 */
public class SceneOperation {

    /** 动作类型。 */
    private final OperationType type;

    /** 设备类型；{@code DELETE} 和 {@code CLEAR_ALL} 时为 {@code null}。 */
    private final DeviceType deviceType;

    /** 目标设备 id；{@code CREATE} 和 {@code CLEAR_ALL} 时为 {@code null}。 */
    private final String targetId;

    /** X 坐标；{@code DELETE} 和 {@code CLEAR_ALL} 时为 {@code null}。 */
    private final Integer x;

    /** Y 坐标；{@code DELETE} 和 {@code CLEAR_ALL} 时为 {@code null}。 */
    private final Integer y;

    /**
     * 模型给出的操作理由。
     *
     * <p>这个字段不参与业务逻辑，但对排查问题很有价值：当用户质疑
     * 「我没让它删东西」时，这里记录了模型当时的理解。</p>
     */
    private final String reason;

    public SceneOperation(OperationType type,
                          DeviceType deviceType,
                          String targetId,
                          Integer x,
                          Integer y,
                          String reason) {
        if (type == null) {
            throw new IllegalArgumentException("type 不能为空");
        }
        this.type = type;
        this.deviceType = deviceType;
        this.targetId = targetId;
        this.x = x;
        this.y = y;
        // reason 允许缺失：模型有时不给理由，这不该让整个操作失败。
        this.reason = (reason == null) ? "" : reason.trim();
    }

    /** 创建操作的便捷构造。 */
    public static SceneOperation create(DeviceType deviceType, int x, int y, String reason) {
        return new SceneOperation(OperationType.CREATE, deviceType, null, x, y, reason);
    }

    /** 移动操作的便捷构造。 */
    public static SceneOperation move(String targetId, int x, int y, String reason) {
        return new SceneOperation(OperationType.MOVE, null, targetId, x, y, reason);
    }

    /** 删除操作的便捷构造。 */
    public static SceneOperation delete(String targetId, String reason) {
        return new SceneOperation(OperationType.DELETE, null, targetId, null, null, reason);
    }

    /** 清空操作的便捷构造。 */
    public static SceneOperation clearAll(String reason) {
        return new SceneOperation(OperationType.CLEAR_ALL, null, null, null, null, reason);
    }

    public OperationType getType() {
        return type;
    }

    public DeviceType getDeviceType() {
        return deviceType;
    }

    public String getTargetId() {
        return targetId;
    }

    public Integer getX() {
        return x;
    }

    public Integer getY() {
        return y;
    }

    public String getReason() {
        return reason;
    }

    /** 是否属于破坏性操作，转发给 {@link OperationType}。 */
    public boolean isDestructive() {
        return type.isDestructive();
    }

    /**
     * 生成给人看的一句话描述。
     *
     * <p>预览功能靠它把操作讲清楚 —— 用户不看 JSON，只看这句话就要能判断
     * 「这是不是我想要的」。</p>
     */
    public String describe() {
        switch (type) {
            case CREATE:
                return "新增 " + deviceType.getWireValue() + " 于坐标 (" + x + ", " + y + ")";
            case MOVE:
                return "移动 " + targetId + " 到坐标 (" + x + ", " + y + ")";
            case DELETE:
                return "删除 " + targetId;
            case CLEAR_ALL:
                return "清空场景内所有设备";
            default:
                return type.getWireValue();
        }
    }

    @Override
    public String toString() {
        return "SceneOperation{" + describe() + ", destructive=" + isDestructive() + "}";
    }
}
