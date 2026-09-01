package learn.agent.llm.skill;

/**
 * 两个 Skill 用了同一个名称。
 *
 * <p><b>这条必须硬失败，不能后来者覆盖前者。</b>「按扫描顺序覆盖」听起来很方便，
 * 但扫描顺序取决于文件系统的目录枚举顺序 —— 换个机器、换个文件系统，
 * 生效的可能就是另一个。于是同一份工作区在两台机器上表现不同，
 * 而这种 bug 从日志里完全看不出来。</p>
 *
 * <p>更要紧的是安全含义：如果覆盖是允许的，那么往工作区里塞一个同名 Skill
 * 就能<b>替换掉</b>一个已有能力的正文，而模型看到的目录条目一字未变。</p>
 *
 * <p>它和其他 Skill 异常的区别是<b>不回传给模型</b> —— 这是部署配置错误，
 * 扫描期就该炸在启动流程里，让人去修目录。</p>
 */
public class DuplicateSkillException extends SkillException {

    private static final long serialVersionUID = 1L;

    public DuplicateSkillException(String message) {
        super(message);
    }
}
