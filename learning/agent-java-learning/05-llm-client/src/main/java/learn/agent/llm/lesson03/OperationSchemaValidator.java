package learn.agent.llm.lesson03;

import java.util.ArrayList;
import java.util.List;

/**
 * 第一层校验：结构校验。
 *
 * <p>这一层只回答一个问题：<b>这个操作对象的字段搭配对不对</b>。</p>
 *
 * <p>它的输入是 {@link OperationJsonParser} 已经解析好的 {@link SceneOperation}，
 * 所以「是不是合法 JSON」「x 是不是数字」这些问题在它之前就解决了。
 * 它专注的是<b>条件必填</b>：不同的操作类型需要不同的字段。</p>
 *
 * <table border="1">
 *   <caption>各操作类型的必填字段</caption>
 *   <tr><th>操作</th><th>deviceType</th><th>targetId</th><th>x / y</th></tr>
 *   <tr><td>{@code create}</td><td>必填</td><td>不需要</td><td>必填</td></tr>
 *   <tr><td>{@code move}</td><td>不需要</td><td>必填</td><td>必填</td></tr>
 *   <tr><td>{@code delete}</td><td>不需要</td><td>必填</td><td>不需要</td></tr>
 *   <tr><td>{@code clear_all}</td><td>不需要</td><td>不需要</td><td>不需要</td></tr>
 * </table>
 *
 * <h2>这一层刻意不做什么</h2>
 *
 * <p>不判断设备是否真的存在、不判断坐标是否落在当前场景边界内、
 * 不判断设备是否受保护。那些<b>依赖运行时数据</b>，属于第二层
 * {@link SceneBusinessValidator}。</p>
 *
 * <p>分层的收益很具体：这个类是<b>纯函数</b>，不需要数据库、不需要场景快照，
 * 所以它的测试不用准备任何环境。而且换一个场景（不同边界、不同设备集合）
 * 时，这一层的规则和测试完全不用改。</p>
 *
 * <h2>为什么手写而不用 JSON Schema 库</h2>
 *
 * <p>生产项目应该用成熟库（Java 常见的是 {@code networknt/json-schema-validator}）。
 * 本课手写是为了让你看清「Schema 校验」不神秘，就是这些条件判断。
 * 之后用库时，你知道它在替你做什么。</p>
 *
 * <p><b>手写的代价</b>要讲清楚：不支持嵌套对象、{@code oneOf}、正则约束，
 * 也不会生成标准错误路径；字段一多就会变成难维护的 {@code if} 堆。
 * 而且 Schema 说明（发给模型的那段文字）和校验代码是两处，必须手动保持同步 ——
 * 用库可以直接把 Schema 序列化给模型，不会漏。</p>
 */
public class OperationSchemaValidator {

    /** targetId 长度上限，防止超长字符串进入下游。 */
    private static final int MAX_TARGET_ID_LENGTH = 64;

    /** 坐标绝对下限。任何场景的坐标都从 0 开始，负数一定是错的。 */
    private static final int MIN_COORDINATE = 0;

    /**
     * 坐标绝对上限。
     *
     * <p>这个值刻意设得比任何真实场景都大：它要拦的不是「稍微越界」，
     * 而是 {@code 999999} 这种明显荒谬的输出。精确的边界检查交给第二层。</p>
     */
    private static final int MAX_COORDINATE = 10000;

    /**
     * 坐标的绝对上限。
     *
     * <p>这是个<b>写死的常量</b>，不是当前场景的宽高 —— 两者的区别是本课的关键。
     * 模型偶尔会输出 {@code 999999} 这种数字，它在任何场景下都荒谬，
     * 不需要查询任何状态就能判定非法，所以属于结构层。</p>
     *
     * <p>「坐标 5000 是否越界」则必须知道场景多大，那是
     * {@link SceneBusinessValidator} 的事。</p>
     *
     * <p>取值比任何真实场景都大：这一层只拦明显荒谬的值，
     * 不替业务层做判断。宁可放过一个可疑值让下一层用真实边界拦，
     * 也不要在这里写一个「看起来差不多」的上限，那会让两层的职责糊掉。</p>
     */
    private static final int MAX_ABSOLUTE_COORDINATE = 100000;

    /**
     * 校验操作的字段搭配。
     *
     * @param operation 已由 {@link OperationJsonParser} 解析出的操作，允许为 {@code null}
     * @return 校验结果；失败时包含<b>全部</b>问题，而不是第一个
     */
    public ValidationResult<SceneOperation> validate(SceneOperation operation) {
        if (operation == null) {
            // 校验器是防线，防线自己不能先抛 NPE。
            return ValidationResult.fail("没有可校验的操作对象");
        }

        // 收集全部错误。原因见 ValidationResult 类文档：
        // 这些错误要发回给模型让它一次改对，逐条返回会多花几轮 token。
        List<String> errors = new ArrayList<String>();

        // reason 对所有操作类型都必填，所以放在 switch 外面统一检查。
        requireReason(operation, errors);

        switch (operation.getType()) {
            case CREATE:
                requireDeviceType(operation, errors);
                requireCoordinates(operation, errors);
                rejectTargetId(operation, errors);
                break;
            case MOVE:
                requireTargetId(operation, errors);
                requireCoordinates(operation, errors);
                break;
            case DELETE:
                requireTargetId(operation, errors);
                rejectCoordinates(operation, errors);
                break;
            case CLEAR_ALL:
                // 清空不需要任何参数。多给了说明模型可能误解了意图。
                rejectTargetId(operation, errors);
                rejectCoordinates(operation, errors);
                break;
            default:
                errors.add("未支持的操作类型：" + operation.getType().getWireValue());
                break;
        }

        if (!errors.isEmpty()) {
            return ValidationResult.fail(errors);
        }
        return ValidationResult.ok(operation);
    }

    /**
     * 所有操作都必须说明理由。
     *
     * <p>这条规则的服务对象不是程序，而是<b>用户</b>。预览界面上
     * 「将删除 camera-2」只说了会发生什么，没说系统为什么这么理解；
     * 加上 reason（「用户要求移除东侧那台摄像头」），用户才能判断
     * 模型有没有听错。</p>
     *
     * <p>没有 reason 的话，用户只能盲目点确认，「预览 → 确认」这道
     * 最后防线就形同虚设。让模型顺手写一句话，成本极低。</p>
     */
    private void requireReason(SceneOperation operation, List<String> errors) {
        String reason = operation.getReason();
        if (reason == null || reason.trim().isEmpty()) {
            errors.add("必须提供 reason，用一句话说明这样操作的理由，供用户在预览时核对");
        }
    }

    /** create 必须说明设备类型，否则不知道要加什么。 */
    private void requireDeviceType(SceneOperation operation, List<String> errors) {
        if (operation.getDeviceType() == null) {
            errors.add("operation=create 时必须提供 deviceType，可选值：" + DeviceType.allWireValues());
        }
    }

    /** move 和 delete 必须指明操作对象。 */
    private void requireTargetId(SceneOperation operation, List<String> errors) {
        String targetId = operation.getTargetId();
        if (targetId == null || targetId.trim().isEmpty()) {
            // 缺少目标 id 是删除类操作里最危险的残缺输入：
            // 如果下游把「id 为空」理解成「不加过滤条件」，就变成全表删除。
            errors.add("operation=" + operation.getType().getWireValue()
                    + " 时必须提供 targetId，用于指明操作哪一台设备");
            return;
        }
        if (targetId.length() > MAX_TARGET_ID_LENGTH) {
            errors.add("targetId 长度不能超过 " + MAX_TARGET_ID_LENGTH + " 个字符");
        }
    }

    /**
     * create 和 move 必须有坐标，且坐标必须在绝对合理范围内。
     *
     * <p>这里的范围检查用的是<b>写死的常量</b>，判断的是「这个数字本身是否荒谬」：
     * 负数一定错，999999 一定错 —— 无论场景多大都成立，所以不需要查询任何状态。</p>
     *
     * <p>请和第二层的边界检查区分开：「坐标 (150, 30) 是否越界」取决于场景
     * 到底是 100x80 还是 200x200，那必须查场景快照，属于
     * {@link SceneBusinessValidator}。</p>
     *
     * <p>为什么两层都要检查坐标：这一层挡掉明显荒谬的值，让错误尽早暴露，
     * 也避免把垃圾数据带进需要查询数据库的下一层（那一层更贵）。
     * 这是分层校验的常见形态 —— 便宜的检查放前面。</p>
     */
    private void requireCoordinates(SceneOperation operation, List<String> errors) {
        if (operation.getX() == null) {
            errors.add("operation=" + operation.getType().getWireValue() + " 时必须提供 x 坐标");
        } else {
            checkCoordinateRange("x", operation.getX(), errors);
        }
        if (operation.getY() == null) {
            errors.add("operation=" + operation.getType().getWireValue() + " 时必须提供 y 坐标");
        } else {
            checkCoordinateRange("y", operation.getY(), errors);
        }
    }

    /**
     * 检查单个坐标是否落在绝对合理范围内。
     *
     * <p>模型偶尔会输出 {@code 999999} 或负数。即使不知道当前场景多大，
     * 这些值也明显不是有效位置 —— 通常是模型把「很远」理解成了一个大数字。</p>
     */
    private void checkCoordinateRange(String fieldName, int value, List<String> errors) {
        if (value < MIN_COORDINATE) {
            errors.add(fieldName + " 坐标不能为负数，当前值：" + value);
        } else if (value > MAX_COORDINATE) {
            errors.add(fieldName + " 坐标 " + value + " 明显超出任何合理场景尺寸（上限 "
                    + MAX_COORDINATE + "）");
        }
    }

    /**
     * delete 和 clear_all 不该带坐标。
     *
     * <p>为什么报错而不是静默忽略：多余字段是<b>信号</b>，说明模型对任务的理解
     * 和契约不一致。带坐标的 delete 很可能是模型想表达 move 却选错了类型。
     * 静默丢掉坐标就按 delete 执行，用户想移动设备，结果设备被删了。</p>
     */
    private void rejectCoordinates(SceneOperation operation, List<String> errors) {
        if (operation.getX() != null || operation.getY() != null) {
            errors.add("operation=" + operation.getType().getWireValue()
                    + " 不需要坐标，请不要提供 x 和 y。如果你想移动设备，请使用 move");
        }
    }

    /** create 和 clear_all 不该带 targetId。 */
    private void rejectTargetId(SceneOperation operation, List<String> errors) {
        if (operation.getTargetId() != null && !operation.getTargetId().trim().isEmpty()) {
            errors.add("operation=" + operation.getType().getWireValue()
                    + " 不需要 targetId，新增设备的 id 由系统分配");
        }
    }

    /**
     * 返回发给模型的格式说明。
     *
     * <p>这段文字会放进 system 消息。它必须和上面的校验规则<b>保持一致</b> ——
     * 这是手写校验的维护负担：改了校验逻辑要记得同步改这段说明。</p>
     */
    public static String schemaDescription() {
        return "只输出一个 JSON 对象，不要加代码围栏，不要加解释文字。字段如下：\n"
                + "  operation:  必填，可选值 " + OperationType.allWireValues() + "\n"
                + "  deviceType: create 时必填，可选值 " + DeviceType.allWireValues() + "\n"
                + "  targetId:   move / delete 时必填，字符串，最长 " + MAX_TARGET_ID_LENGTH + " 字符\n"
                + "  x, y:       create / move 时必填，整数坐标，范围 "
                + MIN_COORDINATE + " ~ " + MAX_COORDINATE + "\n"
                + "  reason:     必填，一句话说明你为什么这样操作（会展示给用户核对）\n"
                + "\n"
                + "示例：{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":10,\"y\":20,\"reason\":\"用户要求在北侧增加雷达\"}";
    }
}
