package learn.agent.llm.skill;

/**
 * 名字格式合法，但目录里没有这个 Skill。
 *
 * <p>和 {@link SkillNameException} 分开，因为模型该做的事不同：名字不合法要改写法，
 * 名字合法但不存在要换一个 —— 后者说明模型<b>凭印象编了一个名字</b>，
 * 而目录就在它的系统提示里。</p>
 */
public class SkillNotFoundException extends SkillException {

    private static final long serialVersionUID = 1L;

    public SkillNotFoundException(String message) {
        super(message);
    }
}
