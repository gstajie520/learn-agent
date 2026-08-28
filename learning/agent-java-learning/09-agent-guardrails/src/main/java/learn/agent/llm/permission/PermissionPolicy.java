package learn.agent.llm.permission;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;

import java.util.ArrayList;
import java.util.List;

/**
 * 权限裁决：把所有参与方的意见收拢成<b>一个</b>最终态。
 *
 * <p>本类是阶段 8 的核心。它要回答的问题只有一个：这次工具调用，执行还是不执行。
 * 难点不在判断，而在<b>怎么合并互相矛盾的意见</b>——规则说放行、Hook 说放行、
 * 但受保护设备的硬边界说拒绝，该听谁的。</p>
 *
 * <h3>候选的收集顺序（刻意固定）</h3>
 * <ol>
 *   <li>受保护设备硬边界（只对 DESTRUCTIVE 且参数里有 targetId 的调用生效）</li>
 *   <li>破坏性默认 ask（{@link ToolEffect#DESTRUCTIVE}）</li>
 *   <li>外部建议（第 7 课 Hook 提的）</li>
 *   <li>注册的规则，按注册顺序</li>
 * </ol>
 *
 * <h3>归约不是「取第一个」，也不是 max 折叠</h3>
 * <p>{@link #strongest} 按 deny → ask → allow <b>三轮独立扫描</b>。
 * 所以 deny 永远压过 ask 和 allow，与声明位置无关。规则顺序只影响
 * <b>同级冲突</b>时你拿到的是谁的 reason 和 source —— 而这两个字段要进审计，
 * 所以同级必须稳定地取最早的那个。</p>
 *
 * <p>这里有个容易写坏的地方：Java 里很自然会写成
 * {@code decisions.stream().max(comparing(d -> priority(d)))}。纯粹看
 * 「最终 behavior 是什么」两种写法结果相同，但 {@code max} 在多个同级候选时
 * 返回哪一个并不保证是第一个，审计里的 source 就会飘。</p>
 *
 * <h3>返回值契约</h3>
 * <p>{@link #decide} <b>只会返回 allow 或 deny</b>。ask 交给 {@link ApprovalProvider}
 * 收敛，passthrough 归一为 allow。中间态不允许离开本类。</p>
 */
public class PermissionPolicy {

    /** 按注册顺序参与裁决的规则。 */
    private final List<PermissionRule> rules;

    /** 把 ask 收敛成最终态的裁决者。为 null 时 ask 一律 deny。 */
    private final ApprovalProvider approval;

    /** 审计落点。可以为 null（本课的第 4 课兼容路径就没有）。 */
    private final AuditSink audit;

    public PermissionPolicy() {
        this(null, null, null);
    }

    public PermissionPolicy(List<PermissionRule> rules,
                            ApprovalProvider approval,
                            AuditSink audit) {
        List<PermissionRule> copy = new ArrayList<PermissionRule>();
        if (rules != null) {
            for (PermissionRule rule : rules) {
                if (rule == null) {
                    throw new PermissionContractException("rules 不能包含 null");
                }
                copy.add(rule);
            }
        }
        this.rules = copy;
        this.approval = approval;
        this.audit = audit;
    }

    /**
     * 裁决一次工具调用。
     *
     * @return 必然是 allow 或 deny
     */
    public PermissionDecision decide(PermissionRequest request) {
        if (request == null) {
            throw new PermissionContractException("request 不能为空");
        }

        List<PermissionDecision> candidates = new ArrayList<PermissionDecision>();

        // 1) 硬边界。这条不可被任何规则、建议或人工审批翻盘。
        PermissionDecision boundary = protectedDeviceBoundary(request);
        if (boundary != null) {
            candidates.add(boundary);
        }

        // 2) 破坏性操作默认需要人裁决。没有任何规则时也要问。
        PermissionDecision destructive = destructiveDefault(request);
        if (destructive != null) {
            candidates.add(destructive);
        }

        // 3) 外部建议（第 7 课 Hook）。只是候选，不是放行。
        candidates.addAll(request.getRecommendations());

        // 4) 规则，按注册顺序。
        for (PermissionRule rule : rules) {
            PermissionDecision decision;
            try {
                decision = rule.evaluate(request);
            } catch (Throwable e) {
                // 规则谓词自己抛了。收紧而不是跳过：一条本该拦住删除的规则
                // 因为 NPE 被忽略，是最坏的失败方式。
                //
                // 这里抓 Throwable 而不是 RuntimeException：一个自我递归的谓词
                // 抛的是 StackOverflowError，它不是 RuntimeException。只抓
                // RuntimeException 的话，这次裁决会带着异常直接窜出 decide()，
                // 结果是「没有 deny、也没有审计记录」—— 恰好是审计要防的那件事。
                decision = new PermissionDecision(PermissionBehavior.DENY,
                        "权限规则执行失败：" + rule.getName(), rule.getName());
            }
            if (decision != null) {
                candidates.add(decision);
            }
        }

        PermissionDecision proposed = strongest(candidates);
        PermissionDecision last;
        if (proposed.getBehavior() == PermissionBehavior.ASK) {
            last = resolveApproval(request, proposed);
        } else if (proposed.getBehavior() == PermissionBehavior.PASSTHROUGH) {
            // 无人反对。归一为放行，并把这件事如实写进 source。
            last = new PermissionDecision(PermissionBehavior.ALLOW,
                    "没有任何权限规则拦下这次请求", "default");
        } else {
            last = proposed;
        }

        // 审计写在最终决定之后、返回之前。所以审计里永远看不到 ask 和 passthrough。
        // 这里刻意不包 try-catch：审计失败必须让整次裁决失败。
        if (audit != null) {
            audit.record(request, last);
        }
        return last;
    }

    /**
     * 受保护设备的硬边界，对应教材里的 workspace 边界。
     *
     * <p>三个条件都满足才生效：工具是 DESTRUCTIVE、参数里有 targetId、
     * 该设备在场景的受保护集合里。只读和写工具不走这层。</p>
     *
     * <p>为什么这条要单独存在而不写成一条普通规则：普通规则可以被删掉、
     * 可以被 Hook 的 allow 建议平级竞争。硬边界永远第一个进候选，
     * 且它给的是 deny —— 而 deny 在归约里压过一切。</p>
     */
    private PermissionDecision protectedDeviceBoundary(PermissionRequest request) {
        ToolDefinition definition = request.getPrepared().getDefinition();
        if (definition.getEffect() != ToolEffect.DESTRUCTIVE) {
            return null;
        }
        // 走快照而不是 getPrepared().getArguments()：硬边界判过的参数
        // 必须和审计记下的参数是同一份内容，否则审计不成立。
        JsonNode arguments = request.getArgumentsSnapshot();
        if (arguments == null || !arguments.has("targetId")) {
            return null;
        }
        JsonNode targetId = arguments.get("targetId");
        if (!targetId.isTextual()) {
            return new PermissionDecision(PermissionBehavior.DENY,
                    "targetId 必须是字符串", "protected-device");
        }
        SceneSnapshot scene = request.getContext().getScene();
        if (scene == null) {
            return null;
        }
        if (scene.isProtected(targetId.asText())) {
            return new PermissionDecision(PermissionBehavior.DENY,
                    "设备 " + targetId.asText() + " 受保护，禁止删除", "protected-device");
        }
        return null;
    }

    /**
     * 破坏性工具默认要人裁决。
     *
     * <p>这是第 5 课那道破坏性闸门的升级：第 5 课直接回传「等待确认」就结束了，
     * 没有人真的来确认。本课把它变成一条 ask，交给 {@link ApprovalProvider}，
     * 于是「确认」这件事有了实际发生的位置。</p>
     */
    private PermissionDecision destructiveDefault(PermissionRequest request) {
        ToolDefinition definition = request.getPrepared().getDefinition();
        if (definition.getEffect() != ToolEffect.DESTRUCTIVE) {
            return null;
        }
        return new PermissionDecision(PermissionBehavior.ASK,
                "不可逆操作需要人工审批", "destructive-default");
    }

    /**
     * 按 deny → ask → allow 三轮扫描取最强的那条。
     *
     * <p>{@code PASSTHROUGH} 候选在这里被完全忽略 —— 它的含义是「弃权」，
     * 弃权票不该参与计票。一个候选都没有（或全是 passthrough）时返回
     * 一条 passthrough，由调用方归一为 allow。</p>
     */
    private static PermissionDecision strongest(List<PermissionDecision> candidates) {
        PermissionBehavior[] order = {
                PermissionBehavior.DENY, PermissionBehavior.ASK, PermissionBehavior.ALLOW};
        for (PermissionBehavior behavior : order) {
            for (PermissionDecision candidate : candidates) {
                if (candidate.getBehavior() == behavior) {
                    return candidate;
                }
            }
        }
        return new PermissionDecision(PermissionBehavior.PASSTHROUGH,
                "没有任何参与方给出决定", "default");
    }

    /**
     * 把一条 ask 交给审批器，收敛成最终态。
     *
     * <p>五种情况全部 fail-closed 成 deny：没有审批器、审批器抛异常、
     * 返回 null、返回 ask、返回 passthrough。<b>默认答案必须是不执行</b> ——
     * 审批环节自己出问题时如果默认放行，等于这道闸门形同虚设。</p>
     */
    private PermissionDecision resolveApproval(PermissionRequest request, PermissionDecision proposed) {
        if (approval == null) {
            return new PermissionDecision(PermissionBehavior.DENY,
                    "需要人工审批但没有配置审批器：" + proposed.getReason(), "approval");
        }
        // 带上那条 ask，审批器才知道「要我确认什么、为什么」。
        PermissionRequest approvalRequest = request.withProposedDecision(proposed);
        PermissionDecision decision;
        try {
            decision = approval.decide(approvalRequest);
        } catch (Throwable e) {
            // 同样抓 Throwable：审批器是外部实现的接口，它抛什么都不该让
            // 这次裁决绕过 fail-closed 和审计。
            return new PermissionDecision(PermissionBehavior.DENY,
                    "审批器执行失败，本次请求被拒绝：" + proposed.getReason(), "approval");
        }
        if (decision == null) {
            return new PermissionDecision(PermissionBehavior.DENY,
                    "审批器返回了空决定，本次请求被拒绝：" + proposed.getReason(), "approval");
        }
        if (decision.getBehavior().isFinal()) {
            return decision;
        }
        // 审批器又返回了 ask 或 passthrough：它没有收敛，等于没裁决。
        // 带上原来那条 ask 的 reason：否则审计里只剩「没给出最终决定」，
        // 看记录的人不知道当时要批的是什么。
        return new PermissionDecision(PermissionBehavior.DENY,
                "审批器没有给出最终决定，本次请求被拒绝：" + proposed.getReason(), "approval");
    }
}
