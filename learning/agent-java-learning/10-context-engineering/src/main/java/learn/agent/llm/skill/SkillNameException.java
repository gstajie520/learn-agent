package learn.agent.llm.skill;

/**
 * 名字本身不合法：超长、不符合 {@code 小写字母-数字-连字符} 规则、或撞上保留组件。
 *
 * <p><b>这个检查必须在碰文件系统之前完成。</b>名字最终会变成路径的一段，
 * 所以「先验证名字、再拼路径」和「先拼路径、再验证」是两件事 ——
 * 后者意味着 {@code ../../etc/passwd} 这种输入已经被拼进了一个真实路径，
 * 只是碰巧还没读。把校验放在前面，坏名字连变成 {@code Path} 对象的机会都没有。</p>
 */
public class SkillNameException extends SkillException {

    private static final long serialVersionUID = 1L;

    public SkillNameException(String message) {
        super(message);
    }
}
