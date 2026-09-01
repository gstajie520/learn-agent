package learn.agent.llm.skill;

/**
 * Skill 领域错误的基类。
 *
 * <p>分成几个子类不是为了好看，是因为<b>它们要被翻译成不同的工具错误码</b>，
 * 而模型看到不同错误码之后该做的事不一样：</p>
 *
 * <table border="1">
 *   <caption>子类与模型应有的反应</caption>
 *   <tr><th>子类</th><th>工具错误码</th><th>模型该怎么办</th></tr>
 *   <tr><td>{@link SkillNotFoundException}</td><td>{@code skill_not_found}</td>
 *       <td>换一个目录里真实存在的名字，或者别用 Skill</td></tr>
 *   <tr><td>{@link SkillManifestException}</td><td>{@code invalid_skill}</td>
 *       <td>换别的 Skill —— 这个坏了，重试同一个没意义</td></tr>
 *   <tr><td>{@link SkillNameException}</td><td>{@code invalid_arguments}</td>
 *       <td>名字本身不合法，照目录里的原样再填一次</td></tr>
 *   <tr><td>{@link DuplicateSkillException}</td><td>（不回传模型）</td>
 *       <td>这是<b>配置错误</b>，扫描期就炸，不该让模型看见</td></tr>
 * </table>
 *
 * <p>最后一行是这组类型划分的理由所在：{@code DuplicateSkillException} 和其他三个
 * 性质不同 —— 前三个是「这次请求不行」，它是「这个工作区装错了」。
 * 让模型去处理一个部署问题，它只会反复重试。</p>
 */
public class SkillException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public SkillException(String message) {
        super(message);
    }
}
