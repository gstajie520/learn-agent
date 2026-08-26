package learn.agent.llm.lesson03;

/**
 * 允许被创建的设备类型。
 *
 * <p>为什么用枚举而不是 {@code String}：模型是<b>生成式</b>的，它会很自然地
 * 输出 "雷达"、"radar"、"Radar"、"radar_v2"、"热成像雷达" 这些看起来都合理的值。
 * 如果字段类型是 String，这些值会一路通到数据库，最后变成一堆没人能统计的脏数据。</p>
 *
 * <p>枚举把「合法取值」这件事变成编译期和解析期都能检查的约束：
 * 不在这个列表里的类型，在校验阶段就被挡住，永远不会进入业务层。</p>
 *
 * <p>这就是「白名单」思路：不是列出禁止什么，而是列出允许什么。
 * 禁止清单永远列不完，允许清单是有限的。</p>
 */
public enum DeviceType {

    /** 雷达。 */
    RADAR("radar"),

    /** 摄像头。 */
    CAMERA("camera"),

    /** 风速仪。 */
    ANEMOMETER("anemometer"),

    /** 围栏。 */
    FENCE("fence");

    /** JSON 里使用的小写字面值。 */
    private final String wireValue;

    DeviceType(String wireValue) {
        this.wireValue = wireValue;
    }

    /** 返回 JSON 中的字面值，例如 {@code "radar"}。 */
    public String getWireValue() {
        return wireValue;
    }

    /**
     * 按 JSON 字面值查找设备类型。
     *
     * <p>返回 {@code null} 而不是抛异常：调用方（校验器）需要把「类型不认识」
     * 收集成一条可读的校验错误，和其他字段错误一起返回给模型，
     * 而不是遇到第一个问题就中断。</p>
     *
     * @param value JSON 中的字面值，允许为 null
     * @return 匹配的设备类型；不认识时返回 {@code null}
     */
    public static DeviceType fromWireValue(String value) {
        if (value == null) {
            return null;
        }
        // 大小写不敏感：模型输出 "RADAR" 或 "Radar" 都接受，
        // 这属于「无害的格式差异」，不必让模型重试。
        for (DeviceType type : values()) {
            if (type.wireValue.equalsIgnoreCase(value.trim())) {
                return type;
            }
        }
        return null;
    }

    /** 返回全部合法字面值，用于错误信息和 Schema 描述。 */
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
