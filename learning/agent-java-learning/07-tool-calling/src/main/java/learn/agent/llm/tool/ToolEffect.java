package learn.agent.llm.tool;

/**
 * 工具的副作用分类。
 *
 * <p>为什么工具定义里必须带这个字段：<b>「模型能不能调这个工具」和
 * 「程序该不该真的执行它」是两个不同的问题</b>。</p>
 *
 * <p>模型只看工具的名字和描述，它没有办法知道 {@code delete_device} 会让
 * 用户丢数据、而 {@code list_devices} 只是查询。风险等级必须由<b>程序</b>
 * 声明，因为只有程序知道 handler 里到底干了什么。</p>
 *
 * <p>这和第 3 课 {@code OperationType.isDestructive()} 是同一个思路：
 * 把「哪些动作危险」做成可测试、可审计的单一事实来源，而不是散落在
 * 各处的 if 判断里。区别是第 3 课判断的是「模型填的表单」，
 * 本课判断的是「模型选的工具」。</p>
 *
 * <p>阶段 8 的权限四态（允许、拒绝、需审批、需确认）就是在这个分类上展开的。
 * 本课只区分「直接执行」和「必须人工确认」两档。</p>
 */
public enum ToolEffect {

    /** 只读查询，不改变任何状态。做错了没有后果，可以直接执行。 */
    READ("read", false),

    /** 会写入数据，但可撤销。本课仍然只生成预览，不落库。 */
    WRITE("write", false),

    /** 不可逆的破坏性操作。<b>永远不允许模型自己触发</b>，必须人工确认。 */
    DESTRUCTIVE("destructive", true);

    /** 日志和审计里使用的字面值。 */
    private final String wireValue;

    /** 是否必须人工确认后才允许真正执行。 */
    private final boolean requiresConfirmation;

    ToolEffect(String wireValue, boolean requiresConfirmation) {
        this.wireValue = wireValue;
        this.requiresConfirmation = requiresConfirmation;
    }

    public String getWireValue() {
        return wireValue;
    }

    /**
     * 是否必须人工确认。
     *
     * <p>返回 {@code true} 时，{@link ToolCallingService} 不会调用 handler，
     * 而是把「等待确认」作为工具结果回传给模型。模型于是能告诉用户
     * 「我准备删除 X，请确认」，而不是删完再说。</p>
     */
    public boolean requiresConfirmation() {
        return requiresConfirmation;
    }
}
