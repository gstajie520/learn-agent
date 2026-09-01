package learn.agent.llm.workspace;

/**
 * 路径越过了工作区边界，或者根本解析不出一个可信的位置。
 *
 * <h3>为什么是异常而不是返回值</h3>
 * <p>这个模块里其他地方的规矩是「模型能改的错回传成结果，程序的错才抛异常」
 * （见工具层的 {@code ToolExecutionResult}）。路径越界看着像前者 ——
 * 模型填了个坏路径，告诉它改一下不就行了？</p>
 *
 * <p>但这里选择抛异常，理由是<b>调用点的性质不同</b>。路径校验不在「回答模型」
 * 的链路上，它在「决定要不要碰磁盘」的链路上。这条链路只有两种正确结局：
 * 拿到一个已经确认安全的路径，或者压根不往下走。返回一个「失败的 Path」
 * 会让调用方多出一条「忘了检查」的路径，而那条路径的代价是真实的文件访问。</p>
 *
 * <p>工具层的 handler 负责把它翻译成给模型看的错误码 —— 翻译的时候
 * <b>不带原始路径</b>，见 {@code SkillRegistry} 的错误映射。</p>
 */
public class WorkspacePathException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public WorkspacePathException(String message) {
        super(message);
    }
}
