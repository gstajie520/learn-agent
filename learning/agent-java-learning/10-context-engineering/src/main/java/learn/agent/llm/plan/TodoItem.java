package learn.agent.llm.plan;

/**
 * 会话计划里的一项任务。
 *
 * <p>只有两个字段：做什么（{@code content}）、做到哪了（{@code status}）。
 * 没有 id、没有创建时间、没有负责人。</p>
 *
 * <h3>为什么没有 id</h3>
 * <p>因为本课的 {@code todo_write} 工具<b>只接受完整快照</b>，不接受增量补丁。
 * id 的唯一用途是「定位要改哪一项」，而完整快照根本不需要定位 —— 整张表被替换掉。
 * 加上 id 反而会引诱后来的人加一个 {@code todo_update(id, status)}，那就回到了
 * 增量模式，而增量模式在长上下文里必然漂移（见 {@link TodoTracker} 的说明）。</p>
 *
 * <h3>为什么是 final 类</h3>
 * <p>和第 6 课的 {@code PermissionDecision} 同一个理由：非 final 的值类允许别人
 * 塞一个子类进来，在第一次 {@code getStatus()} 时返回 {@code IN_PROGRESS}、
 * 第二次返回 {@code COMPLETED}。计划快照是要被断言、被序列化给模型看的东西，
 * 它必须在两次读取之间保持同一个答案。</p>
 */
public final class TodoItem {

    /** 任务描述。已 trim，保证非空。 */
    private final String content;

    /** 任务状态。 */
    private final TodoStatus status;

    /**
     * @param content 任务描述，不能为空（调用方应先经 {@link TodoWriteValidator} 校验）
     * @param status  任务状态，不能为 null
     */
    public TodoItem(String content, TodoStatus status) {
        if (content == null || content.trim().isEmpty()) {
            // 这里抛异常而不是返回错误对象：走到构造函数意味着校验已经过了，
            // 还能撞上空内容，说明是我们自己的代码写错了，不是模型输出的问题。
            throw new IllegalArgumentException("任务描述不能为空");
        }
        if (status == null) {
            throw new IllegalArgumentException("任务状态不能为 null");
        }
        this.content = content.trim();
        this.status = status;
    }

    public String getContent() {
        return content;
    }

    public TodoStatus getStatus() {
        return status;
    }

    /** @return 是否已完成 */
    public boolean isCompleted() {
        return status == TodoStatus.COMPLETED;
    }

    /** @return 是否正在进行 */
    public boolean isInProgress() {
        return status == TodoStatus.IN_PROGRESS;
    }

    @Override
    public String toString() {
        return "[" + status.getWireValue() + "] " + content;
    }
}
