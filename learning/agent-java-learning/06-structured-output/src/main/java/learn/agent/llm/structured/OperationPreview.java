package learn.agent.llm.structured;

/**
 * 校验通过后生成的操作预览。
 *
 * <p><b>这个类的存在本身就是一个设计主张：</b>模型输出通过全部校验之后，
 * 得到的<b>不是</b>「已修改」，而是「将会这样修改」。真实修改需要用户
 * 看过预览并明确确认，由另一条代码路径执行。</p>
 *
 * <h2>为什么值得多这一步</h2>
 *
 * <p>前面两层校验能挡住格式错误、幻觉 id、越界和危险操作，但挡不住一类问题：
 * <b>模型完全理解错了用户的意图，而生成的操作恰好每一项校验都合法。</b></p>
 *
 * <p>用户说「把北侧那台雷达往东移一点」，模型可能移了南侧那台 —— 设备存在、
 * 坐标合法、类型匹配，所有校验都过。只有用户自己能发现这不是他要的。
 * 预览就是给用户这个机会。</p>
 *
 * <p>这也是 Claude Code 这类工具的做法：改文件前先给你看 diff。
 * 模型的判断可以错，但错误在生效之前必须经过人眼。</p>
 *
 * <h2>预览里放什么</h2>
 *
 * <p>放<b>用户能判断对错</b>的信息，不是内部字段的罗列。
 * 「将在 (10.0, 20.0) 新增 2 台摄像头，设备数 3 → 5」比
 * 一段 JSON 更容易发现错误。设备数变化尤其重要 ——
 * 一次操作把设备从 3 台变成 50 台，用户能立刻看出不对。</p>
 */
public class OperationPreview {

    /** 已通过全部校验的操作。 */
    private final SceneOperation operation;

    /** 给用户看的自然语言说明。 */
    private final String summary;

    /** 操作前的设备总数。 */
    private final int deviceCountBefore;

    /** 操作后的设备总数；异常的数量变化容易被用户一眼看出。 */
    private final int deviceCountAfter;

    public OperationPreview(SceneOperation operation,
                            String summary,
                            int deviceCountBefore,
                            int deviceCountAfter) {
        if (operation == null) {
            throw new IllegalArgumentException("operation 不能为空");
        }
        if (summary == null || summary.trim().isEmpty()) {
            throw new IllegalArgumentException("summary 不能为空：预览必须有可读说明，否则用户无法判断");
        }
        this.operation = operation;
        this.summary = summary;
        this.deviceCountBefore = deviceCountBefore;
        this.deviceCountAfter = deviceCountAfter;
    }

    public SceneOperation getOperation() {
        return operation;
    }

    public String getSummary() {
        return summary;
    }

    public int getDeviceCountBefore() {
        return deviceCountBefore;
    }

    public int getDeviceCountAfter() {
        return deviceCountAfter;
    }

    /**
     * 是否会改变设备总数。
     *
     * <p>MOVE 不改变总数，ADD 和 DELETE 会。UI 可以据此决定要不要
     * 特别提示用户注意数量变化。</p>
     */
    public boolean changesDeviceCount() {
        return deviceCountBefore != deviceCountAfter;
    }

    /**
     * 这个操作是否不可逆。
     *
     * <p>委托给 {@link SceneOperation#isDestructive()}，破坏性由操作类型决定
     * （{@code delete} 和 {@code clear_all} 是，{@code create} 和 {@code move} 不是）。</p>
     *
     * <p>预览层要直接暴露这一点，而不是让调用方自己去翻操作类型。理由很实际：
     * 前端要靠它决定确认按钮是普通样式还是红色警告样式。如果需要调用方
     * 自己判断「哪些类型算危险」，那么每个调用点都可能漏判，
     * 而漏判的后果是用户在没有明显警告的情况下点掉了不可逆操作。</p>
     */
    public boolean isDestructive() {
        return operation.isDestructive();
    }

    /** 拼成一段完整的确认提示，供 CLI 或接口直接展示。 */
    public String toConfirmationMessage() {
        StringBuilder sb = new StringBuilder();
        sb.append(summary);
        if (changesDeviceCount()) {
            sb.append("（设备数 ").append(deviceCountBefore)
              .append(" → ").append(deviceCountAfter).append("）");
        }
        // 不可逆操作要显式警告，不能和普通操作用同样的语气。
        if (isDestructive()) {
            sb.append("\n⚠ 这是不可逆操作，执行后无法自动撤销。");
        }
        // 明确告诉用户「还没发生」，避免误以为已经改完了。
        sb.append("\n以上操作尚未执行，确认后才会生效。");
        return sb.toString();
    }

    @Override
    public String toString() {
        return "OperationPreview{" + summary
                + ", deviceCount=" + deviceCountBefore + "->" + deviceCountAfter + "}";
    }
}
