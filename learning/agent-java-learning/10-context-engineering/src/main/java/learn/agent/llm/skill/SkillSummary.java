package learn.agent.llm.skill;

/**
 * 目录里<b>唯一</b>暴露给模型的元数据：名称 + 一行描述。
 *
 * <p>这个类小得像个 DTO，但它承载了本课最核心的那条边界：<b>正文不在这里</b>。
 * 系统提示里只放这两个字段，模型据此判断「要不要加载」，正文要等它真的调用
 * {@code load_skill} 之后才读。</p>
 *
 * <p>如果这个类里多出一个 {@code body} 字段，本课的机制就作废了 ——
 * 因为渲染目录时会顺手把正文一起拼进系统提示，而那正是「硬塞 Prompt」本身。</p>
 */
public final class SkillSummary {

    private final String name;
    private final String description;

    public SkillSummary(String name, String description) {
        if (name == null || name.trim().isEmpty()) {
            throw new IllegalArgumentException("Skill 名称不能为空");
        }
        if (description == null || description.trim().isEmpty()) {
            // 描述是模型做「要不要加载」判断的唯一依据。允许为空等于让它盲选。
            throw new IllegalArgumentException("Skill 描述不能为空：" + name);
        }
        this.name = name;
        this.description = description;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    @Override
    public String toString() {
        return "SkillSummary{" + name + "}";
    }
}
