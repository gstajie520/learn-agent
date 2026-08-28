package learn.agent.llm.lesson06;

/**
 * 把一条 {@code ask} 收敛成 allow 或 deny 的裁决者，通常背后是人。
 *
 * <p>这个接口是本课「不确定性隔离」的第三次应用：第 1 课的 {@code ModelClient}
 * 隔离网络，第 5 课的 {@code TraceIdGenerator} 隔离随机，这里隔离的是
 * <b>人的判断</b>。测试因此可以精确构造「人点了拒绝」「审批器崩了」
 * 这些分支，而不需要真的有人坐在终端前。</p>
 *
 * <p>实现可以是终端问一句 y/n、发一条钉钉审批、或者查一张审批工单表。
 * policy 不关心，它只要一个最终态。</p>
 */
public interface ApprovalProvider {

    /**
     * 裁决一次请求。
     *
     * <p>约定：<b>应当返回 allow 或 deny</b>。如果返回 ask、passthrough 或 null，
     * policy 会一律按 deny 处理（fail-closed）—— 审批器自己都没想清楚的时候，
     * 默认答案必须是「不执行」。</p>
     *
     * @param request 带 {@code proposedDecision}（那条 ask）的请求
     * @return 最终决定
     */
    PermissionDecision decide(PermissionRequest request);
}
