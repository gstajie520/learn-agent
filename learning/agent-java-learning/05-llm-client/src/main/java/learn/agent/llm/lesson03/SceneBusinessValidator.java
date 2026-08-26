package learn.agent.llm.lesson03;

import java.util.ArrayList;
import java.util.List;

/**
 * 第二层校验：业务校验。
 *
 * <p><b>本课最重要的一个类。</b>它存在的理由可以用一句话说清：
 * <b>结构正确不代表业务合法。</b></p>
 *
 * <p>{@code {"operation":"delete","deviceId":"radar-99",...}} 这段 JSON
 * 完美通过第一层 Schema 校验 —— 字段齐全、类型正确、枚举合法。
 * 但如果 {@code radar-99} 根本不存在，或者它是一台正在录制的关键设备，
 * 执行下去就是一次事故。Schema 校验完全看不出这些问题，
 * 因为它不知道<b>当前场景里到底有什么</b>。</p>
 *
 * <h2>两层为什么必须分开</h2>
 *
 * <ul>
 *   <li><b>依赖不同</b>：结构校验只需要 JSON 本身，是纯函数，随时可跑；
 *       业务校验需要读当前场景状态，依赖数据库或缓存；</li>
 *   <li><b>错误性质不同</b>：结构错误是模型「格式没遵守」，可以把错误发回去让它重试；
 *       业务错误是模型「理解有偏差」，重试往往还是错，通常应该直接告诉用户；</li>
 *   <li><b>变化频率不同</b>：Schema 跟着接口版本走，很少变；
 *       业务规则跟着需求走，经常变。</li>
 * </ul>
 *
 * <h2>这一层挡住的四类问题</h2>
 *
 * <ol>
 *   <li><b>引用不存在的对象</b>：模型编了一个 deviceId（幻觉）；</li>
 *   <li><b>越界</b>：坐标数值合法，但超出当前场景的实际边界；</li>
 *   <li><b>危险操作</b>：删除被锁定的关键设备；</li>
 *   <li><b>容量超限</b>：加上这次数量会超过场景设备上限。</li>
 * </ol>
 *
 * <p><b>这一层仍然不做什么：</b>不检查用户权限（阶段 8 的话题），
 * 不做审计留痕，也不真正修改数据 —— 校验通过只生成预览，
 * 见 {@link OperationPreview}。</p>
 */
public class SceneBusinessValidator {

    /** 当前场景快照，业务校验的事实依据。 */
    private final SceneSnapshot snapshot;

    public SceneBusinessValidator(SceneSnapshot snapshot) {
        if (snapshot == null) {
            throw new IllegalArgumentException("snapshot 不能为空：没有场景状态就无法做业务校验");
        }
        this.snapshot = snapshot;
    }

    /**
     * 校验一个已通过结构校验的操作，生成可供用户确认的预览。
     *
     * <p><b>关键设计：成功也不执行。</b>返回的是 {@link OperationPreview}，
     * 一份「如果确认，将会发生什么」的说明。真正的修改需要用户确认后
     * 由另一条代码路径执行。这是防止模型误操作的最后一道，也是最有效的一道防线：
     * 即使前面所有校验都被绕过，用户还有机会看一眼再点确认。</p>
     *
     * @param operation 已通过 {@link OperationSchemaValidator} 的操作，允许为 {@code null}
     * @return 校验结果；成功时携带预览，失败时携带全部业务问题
     */
    public ValidationResult<OperationPreview> validate(SceneOperation operation) {
        if (operation == null) {
            // 和 OperationSchemaValidator 保持一致：校验器是防线，防线自己不能先抛 NPE。
            // 两层如果一层抛异常、一层返回失败，调用方就得同时写 try/catch 和结果判断，
            // 很容易漏掉一种，漏掉的那种就变成 500。
            return ValidationResult.fail("没有可校验的操作对象");
        }

        List<String> errors = new ArrayList<String>();

        // 规则 1：坐标必须落在当前场景的实际边界内。
        // 注意这和 Schema 层的范围检查不是一回事：
        // Schema 检查的是「这个数字是否荒谬」（写死的常量 ±10000），
        // 这里检查的是「这个位置在当前场景里是否存在」（依赖场景状态）。
        // 同一个坐标 (500, 500) 在 1000x1000 的场景里合法，在 200x200 的场景里非法。
        if (operation.getX() != null && operation.getY() != null) {
            if (!snapshot.isInsideBounds(operation.getX(), operation.getY())) {
                errors.add("坐标 (" + operation.getX() + ", " + operation.getY()
                        + ") 超出当前场景边界，合法范围：" + snapshot.describeBounds());
            }
        }

        // 规则 2：按操作类型分别校验。
        switch (operation.getType()) {
            case CREATE:
                validateCreate(operation, errors);
                break;
            case MOVE:
                validateMove(operation, errors);
                break;
            case DELETE:
                validateDelete(operation, errors);
                break;
            case CLEAR_ALL:
                validateClearAll(operation, errors);
                break;
            default:
                errors.add("未处理的操作类型：" + operation.getType().getWireValue());
                break;
        }

        if (!errors.isEmpty()) {
            return ValidationResult.fail(errors);
        }

        // 全部通过，生成预览。再强调一次：这里没有任何写操作。
        return ValidationResult.ok(buildPreview(operation));
    }

    /** 新增设备：检查容量上限。 */
    private void validateCreate(SceneOperation operation, List<String> errors) {
        if (snapshot.isFull()) {
            errors.add("场景已达设备上限 " + snapshot.getMaxDevices()
                    + " 台，无法继续新增。请先删除不需要的设备");
        }
    }

    /** 移动设备：设备必须存在，且类型要对得上。 */
    private void validateMove(SceneOperation operation, List<String> errors) {
        if (!snapshot.hasDevice(operation.getTargetId())) {
            // 这是最典型的模型幻觉：编一个格式正确但不存在的 id。
            // 把真实的 id 列表告诉它，下一轮就有机会改对。
            errors.add("设备 " + operation.getTargetId() + " 不存在，无法移动。当前场景设备："
                    + snapshot.describeDeviceIds());
        }
    }

    /** 删除设备：设备必须存在，且不能是受保护的关键设备。 */
    private void validateDelete(SceneOperation operation, List<String> errors) {
        if (!snapshot.hasDevice(operation.getTargetId())) {
            errors.add("设备 " + operation.getTargetId() + " 不存在，无法删除。当前场景设备："
                    + snapshot.describeDeviceIds());
            return;
        }
        if (snapshot.isProtected(operation.getTargetId())) {
            // 危险操作拦截。保护名单由业务方维护，模型无权跨过它。
            // 这条规则只能写在代码里 —— 写在提示词里只是「请求」，不是「保证」。
            errors.add("设备 " + operation.getTargetId()
                    + " 是受保护的关键设备，不允许通过自然语言指令删除。如确需删除请走人工流程");
        }
    }

    /**
     * 清空全部设备：破坏性最强的操作。
     *
     * <p>只要场景里有任何受保护设备，就整体拒绝 —— 而不是「删掉其余的」。
     * 因为用户说「清空」时，他很可能没意识到里面有关键设备。
     * 部分执行会产生一个用户没预期的中间状态，比直接拒绝更糟。</p>
     */
    private void validateClearAll(SceneOperation operation, List<String> errors) {
        if (snapshot.getDeviceCount() == 0) {
            errors.add("场景本来就没有设备，无需清空");
            return;
        }
        if (!snapshot.getProtectedDeviceIds().isEmpty()) {
            errors.add("场景包含受保护设备 " + snapshot.getProtectedDeviceIds()
                    + "，不允许整体清空。请逐台指定要删除的设备");
        }
    }

    /**
     * 组装预览文本，让用户能一眼看懂「确认之后会发生什么」。
     *
     * <p>预览里带上设备数量变化，是因为数量的异常变化最容易被用户察觉。
     * 「3 → 4」正常，「3 → 0」就该停下来想一想。</p>
     */
    private OperationPreview buildPreview(SceneOperation operation) {
        int before = snapshot.getDeviceCount();
        String summary;
        int countAfter;

        switch (operation.getType()) {
            case CREATE:
                summary = "将在坐标 (" + operation.getX() + ", " + operation.getY()
                        + ") 新增一台" + operation.getDeviceType().getWireValue();
                countAfter = before + 1;
                break;
            case MOVE:
                summary = "将把 " + operation.getTargetId()
                        + " 移动到坐标 (" + operation.getX() + ", " + operation.getY() + ")";
                // 移动不改变设备总数。
                countAfter = before;
                break;
            case DELETE:
                summary = "将删除设备 " + operation.getTargetId()
                        + "（类型：" + snapshot.getDeviceType(operation.getTargetId()).getWireValue() + "）";
                countAfter = before - 1;
                break;
            case CLEAR_ALL:
                summary = "将清空场景内全部 " + before + " 台设备";
                countAfter = 0;
                break;
            default:
                throw new IllegalStateException("未处理的操作类型：" + operation.getType().getWireValue());
        }

        return new OperationPreview(operation, summary, before, countAfter);
    }
}
