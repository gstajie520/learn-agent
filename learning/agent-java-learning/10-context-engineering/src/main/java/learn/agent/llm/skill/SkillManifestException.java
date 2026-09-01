package learn.agent.llm.skill;

/**
 * {@code SKILL.md} 本身不合规：缺 frontmatter、字段缺失、名称与目录名不一致、
 * 或者内容不是合法 UTF-8。
 *
 * <p><b>为什么「名称与目录名不一致」算 manifest 错误而不是找不到。</b>
 * 目录名是模型在目录里看到的那个名字，frontmatter 里的 name 是文件自己声明的。
 * 两者不一致时，一个叫 {@code deploy-guide} 的目录可以声明自己是
 * {@code safe-readonly-guide} —— 模型以为加载的是后者，实际读到的是前者的正文。
 * 这是<b>身份冒充</b>，必须硬失败，不能取其中一个当准。</p>
 */
public class SkillManifestException extends SkillException {

    private static final long serialVersionUID = 1L;

    public SkillManifestException(String message) {
        super(message);
    }
}
