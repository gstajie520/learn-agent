package learn.agent.llm.permission;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolContext;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 提交给权限层裁决的一次请求。
 *
 * <p>为什么传的是 {@link PreparedToolCall} 而不是原始的 {@code ToolCall}：
 * 权限判断经常要看参数（删的是哪台设备），而参数只有过了 prepare 才是
 * 解析并校验过的。让规则自己去解析 JSON，等于把第 5 课的四道边界
 * 又散回各条规则里。</p>
 *
 * <p>{@code recommendations} 是给第 7 课 Hook 预留的口子：Hook 可以提建议，
 * 但建议只是候选之一，最终仍由 policy 归约 —— <b>Hook 的 allow 不是放行</b>。</p>
 */
public final class PermissionRequest {

    /** 已解析、已校验、还未执行的调用。 */
    private final PreparedToolCall prepared;

    /** 程序提供的受控环境（身份 + 场景快照）。 */
    private final ToolContext context;

    /** 外部参与方（第 7 课的 Hook）提出的候选决定。 */
    private final List<PermissionDecision> recommendations;

    /** 交给审批器时填上的那条 ask，让审批器知道「要我确认什么、为什么」。 */
    private final PermissionDecision proposedDecision;

    public PermissionRequest(PreparedToolCall prepared, ToolContext context) {
        this(prepared, context, null, null);
    }

    public PermissionRequest(PreparedToolCall prepared,
                             ToolContext context,
                             List<PermissionDecision> recommendations,
                             PermissionDecision proposedDecision) {
        if (prepared == null) {
            throw new PermissionContractException("prepared 不能为空");
        }
        if (prepared.isFailed()) {
            // prepare 就失败的调用不该走到权限层：白名单/参数问题已经有答案了，
            // 再问一遍权限只会让审计里多出一堆无意义记录。
            throw new PermissionContractException("prepare 已失败的调用不应进入权限裁决");
        }
        if (context == null) {
            throw new PermissionContractException("context 不能为空");
        }
        // proposedDecision 只能是 ask：它的唯一用途就是告诉审批器「这条 ask 要你裁决」。
        if (proposedDecision != null && proposedDecision.getBehavior() != PermissionBehavior.ASK) {
            throw new PermissionContractException(
                    "proposedDecision 必须是一条 ask，当前是 " + proposedDecision.getBehavior().getWireValue());
        }
        List<PermissionDecision> copy = new ArrayList<PermissionDecision>();
        if (recommendations != null) {
            for (PermissionDecision d : recommendations) {
                if (d == null) {
                    throw new PermissionContractException("recommendations 不能包含 null");
                }
                copy.add(d);
            }
        }
        this.prepared = prepared;
        this.context = context;
        this.recommendations = Collections.unmodifiableList(copy);
        this.proposedDecision = proposedDecision;
    }

    /** 复制一份并填上待审批的那条 ask。 */
    public PermissionRequest withProposedDecision(PermissionDecision proposed) {
        return new PermissionRequest(prepared, context, recommendations, proposed);
    }

    public PreparedToolCall getPrepared() {
        return prepared;
    }

    public ToolContext getContext() {
        return context;
    }

    public List<PermissionDecision> getRecommendations() {
        return recommendations;
    }

    public PermissionDecision getProposedDecision() {
        return proposedDecision;
    }

    /** 工具名，规则里用得最多，给个直接入口。 */
    public String getToolName() {
        return prepared.getDefinition().getName();
    }

    /**
     * 参数的<b>快照副本</b>。规则要读参数，应该走这里，不要走
     * {@code getPrepared().getArguments()}。
     *
     * <p>为什么要复制：{@code PreparedToolCall} 里的 {@code arguments} 是一个
     * 活的 {@code ObjectNode}。一条规则完全可以写成
     * {@code ((ObjectNode) req.getPrepared().getArguments()).remove("targetId")} ——
     * 于是硬边界判过的参数和审计记下的参数就不是同一份东西了。审计要成立，
     * 前提是「被裁决的那次调用」和「被记录的那次调用」一模一样。</p>
     *
     * <p><b>这个洞没有被完全堵上，如实说明：</b>{@link #getPrepared()} 仍然
     *返回原对象，规则绕过本方法就还能改到原参数。要彻底堵住，得让第 4 课的
     * {@code PreparedToolCall.getArguments()} 自己返回副本 —— 那是第 4 课的
     * 修改，本课不回头动已经讲完的代码。这类「深层不可变」的缺口在 TS 和
     * Python 版里也一样存在（{@code Object.freeze} 是浅的，frozen dataclass
     * 也不深冻），属于继承来的问题，不是本课新引入的。</p>
     */
    public JsonNode getArgumentsSnapshot() {
        JsonNode arguments = prepared.getArguments();
        return arguments == null ? null : arguments.deepCopy();
    }

    @Override
    public String toString() {
        return "PermissionRequest{tool=" + getToolName()
                + ", identity=" + context.getIdentity()
                + ", recommendations=" + recommendations.size() + "}";
    }
}
