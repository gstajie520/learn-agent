package learn.agent.llm.lesson03;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * 场景当前状态的只读快照。
 *
 * <p>它存在的理由只有一个：<b>业务校验需要知道「现在有什么」</b>。</p>
 *
 * <p>格式校验只能看 JSON 本身，判断不了「这个设备到底存不存在」。
 * 模型说「把 device-99 移到 (10,20)」，JSON 完全合法，但如果场景里
 * 根本没有 device-99，这个操作就是错的。判断这一点必须对照真实状态。</p>
 *
 * <p>这正是「结构正确 ≠ 业务合法」的具体体现，也是本课最重要的一条结论。</p>
 *
 * <p>快照是<b>不可变</b>的：校验期间场景不应该变。真实系统里这个快照
 * 通常来自数据库或 Redis（阶段 4 学过），并且要带版本号做乐观锁 ——
 * 否则校验通过到真正执行之间，场景可能已经被别人改了。
 * 本课先不引入版本号，专注在校验分层本身。</p>
 */
public class SceneSnapshot {

    /** 场景边界宽度，坐标合法范围是 {@code [0, width)}。 */
    private final int width;

    /** 场景边界高度，坐标合法范围是 {@code [0, height)}。 */
    private final int height;

    /** 已存在的设备：id → 类型。使用 LinkedHashMap 保持插入顺序，让输出稳定可测。 */
    private final Map<String, DeviceType> devices;

    /**
     * 受保护设备的 id 集合。
     *
     * <p>这些设备不允许通过自然语言指令删除。为什么需要这个概念：
     * 用户说「把场景清理一下」，模型可能理解成删除全部设备，
     * 连门禁、主控这类关键设备一起删掉。</p>
     *
     * <p><b>关键点：这个约束不能只写在提示词里。</b>提示词是「请求」，
     * 模型可能不遵守；代码校验才是「保证」。所以保护名单必须在
     * 程序侧强制执行。</p>
     */
    private final Set<String> protectedDeviceIds;

    /** 单个场景允许的最大设备数量，防止模型批量生成把场景撑爆。 */
    private final int maxDevices;

    public SceneSnapshot(int width, int height, int maxDevices, Map<String, DeviceType> devices) {
        this(width, height, maxDevices, devices, null);
    }

    public SceneSnapshot(int width,
                         int height,
                         int maxDevices,
                         Map<String, DeviceType> devices,
                         Set<String> protectedDeviceIds) {
        if (width <= 0 || height <= 0) {
            throw new IllegalArgumentException("场景宽高必须为正数");
        }
        if (maxDevices <= 0) {
            throw new IllegalArgumentException("maxDevices 必须为正数");
        }
        this.width = width;
        this.height = height;
        this.maxDevices = maxDevices;
        // 先复制再包装成只读：防止外部继续修改传入的 Map 影响这个快照。
        this.devices = Collections.unmodifiableMap(
                new LinkedHashMap<String, DeviceType>(devices == null ? new LinkedHashMap<String, DeviceType>() : devices));
        this.protectedDeviceIds = Collections.unmodifiableSet(
                new LinkedHashSet<String>(protectedDeviceIds == null ? new LinkedHashSet<String>() : protectedDeviceIds));
    }

    /** 创建一个便于测试的空场景。 */
    public static SceneSnapshot empty(int width, int height, int maxDevices) {
        return new SceneSnapshot(width, height, maxDevices, new LinkedHashMap<String, DeviceType>());
    }

    public int getWidth() {
        return width;
    }

    public int getHeight() {
        return height;
    }

    public int getMaxDevices() {
        return maxDevices;
    }

    /** 返回只读设备表。 */
    public Map<String, DeviceType> getDevices() {
        return devices;
    }

    /** 设备是否存在。业务校验靠它判断 MOVE/DELETE 的目标是否真实存在。 */
    public boolean hasDevice(String deviceId) {
        return deviceId != null && devices.containsKey(deviceId);
    }

    /** 查设备类型；不存在时返回 {@code null}。 */
    public DeviceType getDeviceType(String deviceId) {
        return deviceId == null ? null : devices.get(deviceId);
    }

    /**
     * 设备是否受保护（禁止删除）。
     *
     * <p>业务校验用它拦住「删除关键设备」这类危险操作。</p>
     */
    public boolean isProtected(String deviceId) {
        return deviceId != null && protectedDeviceIds.contains(deviceId);
    }

    /** 返回只读的受保护设备 id 集合。 */
    public Set<String> getProtectedDeviceIds() {
        return protectedDeviceIds;
    }

    /**
     * 列出当前设备 id，用于校验失败时的提示。
     *
     * <p>把真实存在的 id 告诉模型，它下一轮就有机会改对，
     * 而不是继续猜。这比只说「设备不存在」有用得多。</p>
     */
    public String describeDeviceIds() {
        return devices.isEmpty() ? "（当前场景没有设备）" : devices.keySet().toString();
    }

    /** 描述场景边界，用于越界错误提示。 */
    public String describeBounds() {
        return "0 ≤ x < " + width + "，0 ≤ y < " + height;
    }

    /** 当前设备数量。 */
    public int getDeviceCount() {
        return devices.size();
    }

    /** 是否已达设备上限。 */
    public boolean isFull() {
        return devices.size() >= maxDevices;
    }

    /**
     * 坐标是否在场景边界内。
     *
     * <p>合法范围是 {@code [0, width)} 和 {@code [0, height)}，
     * 右边界和下边界取不到 —— 和数组下标一样的约定。</p>
     */
    public boolean isInsideBounds(int x, int y) {
        return x >= 0 && x < width && y >= 0 && y < height;
    }

    @Override
    public String toString() {
        return "SceneSnapshot{" + width + "x" + height
                + ", devices=" + devices.size() + "/" + maxDevices
                + ", ids=" + devices.keySet() + "}";
    }
}
