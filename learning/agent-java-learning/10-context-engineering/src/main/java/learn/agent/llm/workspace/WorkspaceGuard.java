package learn.agent.llm.workspace;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 工作区边界：所有「要碰磁盘」的路径都必须先过这里。
 *
 * <h3>这一层为什么必须存在</h3>
 * <p>Agent 的工具参数是<b>模型生成的字符串</b>。一个 {@code read_file} 工具
 * 如果直接把模型给的路径交给 {@code Files.readAllBytes}，那么模型返回
 * {@code ../../../.ssh/id_rsa} 就能读到工作区外的私钥 —— 而这不需要模型「怀有恶意」，
 * 提示词注入、或者模型只是把相对路径算错了，都会走到同一个地方。</p>
 *
 * <p>这一层是本工程<b>第一次</b>引入文件访问。前面几个阶段刻意把教材的
 * 「文件 / shell 工作区」域换成了「场景 / 设备」域，代价是路径安全这一课一直没学到。
 * 阶段 9 的后三课（Skill 按需加载、产物落盘、文件记忆）机制本体都是文件系统，
 * 所以在这里把这一课补回来，后两课直接复用本类。</p>
 *
 * <h3>两道关，缺一不可</h3>
 * <table border="1">
 *   <caption>词法关与物理关的分工</caption>
 *   <tr><th></th><th>词法关（不碰磁盘）</th><th>物理关（必须碰磁盘）</th></tr>
 *   <tr><td>做什么</td><td>看字符串本身合不合法</td><td>解析真实路径，看它落在哪</td></tr>
 *   <tr><td>方法</td><td>{@link #resolveRelative}</td>
 *       <td>{@link #realDirectoryInside}、{@link #realFileInside}</td></tr>
 *   <tr><td>能挡住</td><td>绝对路径、{@code ..}、保留设备名、控制字符</td>
 *       <td>符号链接 / junction 指向区外</td></tr>
 *   <tr><td>挡不住</td><td>符号链接 —— 字符串上完全合法</td>
 *       <td>不存在的路径（还没创建时无法 realpath）</td></tr>
 * </table>
 *
 * <p><b>只做词法关是不够的</b>：{@code skills/evil} 这个字符串挑不出任何毛病，
 * 但它可以是一个指向 {@code C:\Windows} 的目录联接。反过来<b>只做物理关也不够</b>：
 * 要新建的文件还不存在，{@code toRealPath} 直接抛异常，此时只能靠词法关。</p>
 */
public final class WorkspaceGuard {

    /** 单个路径组件的长度上限。防止超长名字在不同文件系统上被静默截断。 */
    public static final int MAX_COMPONENT_LENGTH = 255;

    /** Windows 保留设备名。在这些名字上做文件操作会打到设备而不是文件。 */
    private static final Set<String> WINDOWS_DEVICE_NAMES = Collections.unmodifiableSet(
            new HashSet<String>(Arrays.asList(
                    "CON", "PRN", "AUX", "NUL",
                    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9")));

    /** 已解析成真实路径的工作区根，绝对且规范。 */
    private final Path root;

    private WorkspaceGuard(Path root) {
        this.root = root;
    }

    /**
     * 打开一个工作区。
     *
     * <p>立刻做两件事：解析真实路径、确认它是目录。<b>在构造期就解析</b>，
     * 是为了让后续每一次包含性检查都有一个规范的、不含链接的基准 ——
     * 如果 root 本身是个链接，那么「在 root 之内」这句话就没有确定含义。</p>
     *
     * @param workspace 工作区路径，可以是相对的
     * @throws WorkspacePathException 路径不存在、不是目录，或解析失败
     */
    public static WorkspaceGuard open(String workspace) {
        if (workspace == null || workspace.trim().isEmpty()) {
            throw new WorkspacePathException("工作区路径不能为空");
        }
        Path candidate;
        try {
            candidate = Paths.get(workspace);
        } catch (InvalidPathException e) {
            // Windows 上带 NUL 或非法字符的字符串在这里就会失败。
            throw new WorkspacePathException("工作区路径不合法：" + workspace);
        }
        Path real;
        try {
            real = candidate.toRealPath();
        } catch (IOException e) {
            throw new WorkspacePathException("工作区不存在或无法解析：" + workspace);
        }
        if (!Files.isDirectory(real, LinkOption.NOFOLLOW_LINKS)) {
            throw new WorkspacePathException("工作区不是目录：" + workspace);
        }
        return new WorkspaceGuard(real);
    }

    /** @return 工作区根的真实路径，绝对且规范 */
    public Path getRoot() {
        return root;
    }

    /**
     * 词法关：把一个<b>相对</b>路径拼到工作区之下，不要求目标已经存在。
     *
     * <p>逐条拒绝的东西见下表。每一条都对应一种「字符串看着没问题、
     * 拼出来却在区外」的情形。</p>
     *
     * <table border="1">
     *   <caption>词法关拒绝什么、为什么</caption>
     *   <tr><th>拒绝</th><th>不拒的后果</th></tr>
     *   <tr><td>空串 / 全空白</td><td>拼出来就是工作区根本身，调用方以为拿到了子路径</td></tr>
     *   <tr><td>NUL 与控制字符</td><td>底层 API 可能在 NUL 处截断，校验的和实际打开的不是同一个路径</td></tr>
     *   <tr><td>绝对路径（{@code /x}、{@code C:\x}、{@code \\host\share}）</td>
     *       <td>{@code resolve} 遇到绝对路径会<b>整段替换</b>，工作区根被彻底丢掉</td></tr>
     *   <tr><td>{@code ..} 组件</td><td>典型逃逸：{@code ../../etc/passwd}</td></tr>
     *   <tr><td>Windows 保留设备名</td><td>打到设备而不是文件，行为完全不可预期</td></tr>
     *   <tr><td>超长组件</td><td>不同文件系统截断长度不同，可能撞到别的文件</td></tr>
     * </table>
     *
     * <p><b>{@code ..} 必须按组件判，不能用字符串包含判。</b>用
     * {@code contains("..")} 会把 {@code my..file} 这个合法名字也拒掉，
     * 而真正的逃逸是独立的一段 {@code ..}。反过来只查开头
     * （{@code startsWith("..")}）会漏掉 {@code a/../../b}。</p>
     *
     * <p><b>两种分隔符都要认。</b>模型分不清自己在什么系统上，
     * {@code skills\demo} 和 {@code skills/demo} 都会出现。只认一种的话，
     * 另一种会被当成<b>单个文件名</b>，于是 {@code ..\..\etc} 整串变成一个
     * 「文件名」躲过组件检查。</p>
     *
     * @param relativePath 工作区内的相对路径
     * @return 拼好的绝对路径（未做物理检查，目标可以不存在）
     * @throws WorkspacePathException 任一条词法规则不通过
     */
    public Path resolveRelative(String relativePath) {
        List<String> parts = splitAndValidate(relativePath);
        Path resolved = root;
        for (String part : parts) {
            resolved = resolved.resolve(part);
        }
        // normalize 之后再确认一次还在区内。到这一步 parts 里已经没有 ".."，
        // 这句是纵深防御：万一上面的拆分逻辑将来被改坏，这里还能兜住。
        Path normalized = resolved.normalize();
        if (!isInside(root, normalized)) {
            throw new WorkspacePathException("路径越出工作区：" + relativePath);
        }
        return normalized;
    }

    /** 把相对路径拆成组件并逐条过词法关。返回的组件里保证没有 {@code .} 和 {@code ..}。 */
    private static List<String> splitAndValidate(String relativePath) {
        if (relativePath == null || relativePath.trim().isEmpty()) {
            throw new WorkspacePathException("相对路径不能为空");
        }
        if (relativePath.indexOf('\0') >= 0) {
            throw new WorkspacePathException("路径不能包含 NUL 字符");
        }
        // 先统一分隔符，再判绝对路径 —— 顺序不能反：
        // "\\server\share" 在统一之前是 UNC，统一之后才好按段检查。
        String unified = relativePath.replace('\\', '/');
        if (unified.startsWith("/") || unified.startsWith("//")) {
            throw new WorkspacePathException("路径必须是相对的：" + relativePath);
        }
        // Windows 盘符：C:、c:foo 都算绝对（后者是「盘符相对」，同样危险）。
        if (unified.length() >= 2 && unified.charAt(1) == ':'
                && Character.isLetter(unified.charAt(0))) {
            throw new WorkspacePathException("路径必须是相对的：" + relativePath);
        }

        List<String> parts = new ArrayList<String>();
        for (String raw : unified.split("/")) {
            if (raw.isEmpty() || ".".equals(raw)) {
                continue; // 空段和当前目录段没有语义，直接丢
            }
            if ("..".equals(raw)) {
                throw new WorkspacePathException("路径不能包含父级组件：" + relativePath);
            }
            if (raw.length() > MAX_COMPONENT_LENGTH) {
                throw new WorkspacePathException("路径组件过长：" + raw.length() + " 字符");
            }
            if (isReservedComponent(raw)) {
                throw new WorkspacePathException("路径包含保留组件：" + raw);
            }
            parts.add(raw);
        }
        if (parts.isEmpty()) {
            // "./" 或 "///" 这类输入拆完什么都不剩，等于指向工作区根。
            throw new WorkspacePathException("相对路径没有指向任何子路径：" + relativePath);
        }
        return parts;
    }

    /**
     * 这个组件是不是 Windows 上的危险名字。
     *
     * <p>四类都要查，而且<b>在 Linux 上也要查</b> —— 教学工程要在两个平台上
     * 行为一致，否则「本机测试通过、换台机器出问题」是最难查的那种 bug。</p>
     *
     * <ol>
     *   <li><b>尾随空格或点号</b>：Windows 会静默去掉它们，于是 {@code "note.txt "}
     *       和 {@code "note.txt"} 指向同一个文件 —— 校验的和打开的不是一个名字；</li>
     *   <li><b>控制字符和 {@code <>:"|*?}</b>：Windows 直接不允许，
     *       各文件系统的处理还不一致；</li>
     *   <li><b>保留设备名</b>：{@code CON}、{@code NUL}、{@code COM1} 这些是设备，
     *       不是文件。往 {@code NUL} 写入会被丢弃，读 {@code CON} 会去等控制台输入；</li>
     *   <li><b>带扩展名的保留名</b>：{@code CON.txt} 仍然指向设备 ——
     *       这是最容易漏的一条，只查全等会漏掉它。</li>
     * </ol>
     */
    public static boolean isReservedComponent(String component) {
        if (component == null || component.isEmpty()) {
            return true;
        }
        if (component.endsWith(" ") || component.endsWith(".")) {
            return true;
        }
        for (int i = 0; i < component.length(); i++) {
            char c = component.charAt(i);
            if (c < 32 || "<>:\"|*?".indexOf(c) >= 0) {
                return true;
            }
        }
        // 取第一个点之前的部分：CON.txt 的设备名部分是 CON。
        int dot = component.indexOf('.');
        String stem = dot < 0 ? component : component.substring(0, dot);
        // 尾随空格已在上面拒了，这里再 trim 一次是防 "CON .txt" 这种写法。
        stem = stem.replaceAll(" +$", "").toUpperCase(Locale.ROOT);
        return WINDOWS_DEVICE_NAMES.contains(stem);
    }

    /**
     * 纯词法的包含性判断：{@code candidate} 是否在 {@code parent} 之内或就是它。
     *
     * <p>用 {@link Path#startsWith} 而不是字符串前缀比较。字符串比较会把
     * {@code /work-evil} 判成在 {@code /work} 之内 —— 前缀匹配上了，
     * 但那是两个完全不同的目录。{@code Path.startsWith} 按<b>组件</b>比较，
     * 不会犯这个错。</p>
     */
    public static boolean isInside(Path parent, Path candidate) {
        if (parent == null || candidate == null) {
            return false;
        }
        return candidate.normalize().startsWith(parent.normalize());
    }

    /**
     * 物理关：解析真实路径，要求它仍在 {@code parent} 之内，且是<b>目录</b>。
     *
     * <p>这一关词法关替代不了。{@code skills/demo} 这个字符串挑不出毛病，
     * 但它可以是一个指向 {@code C:\Windows} 的目录联接（junction）或符号链接。
     * {@code toRealPath()} 会把链接解开，于是真实位置暴露出来。</p>
     *
     * <p><b>为什么每次访问前都要重新调这个方法，而不是扫描时查一次存起来。</b>
     * 扫描和真正读取之间有时间差。攻击者（或一个恰好在同步文件的进程）可以在这个
     * 窗口里把一个合法目录换成指向区外的链接 —— 这就是 TOCTOU
     * （check 的时刻和 use 的时刻不是同一刻）。存下来的「已验证路径」在那一刻就过期了。
     * 重新解析不能消灭这个窗口，但能把它压到最小。</p>
     *
     * @param candidate 待检查的路径
     * @param parent    必须落在其内的父目录（应当已是真实路径）
     * @return 解析后的真实路径
     * @throws WorkspacePathException 解析失败、落在 parent 之外，或不是目录
     */
    public static Path realDirectoryInside(Path candidate, Path parent) {
        Path real = toRealOrFail(candidate);
        if (!isInside(parent, real) || !Files.isDirectory(real, LinkOption.NOFOLLOW_LINKS)) {
            // 错误信息刻意不含真实路径：这条异常会被工具层翻译给模型看，
            // 而「你要的东西实际在 C:\Windows」本身就是一次信息泄漏。
            throw new WorkspacePathException("目录不在允许范围内，或不是目录");
        }
        return real;
    }

    /**
     * 物理关的文件版本：解析真实路径，要求仍在 {@code parent} 内且是<b>普通文件</b>。
     *
     * <p>「是普通文件」这一条不能省。目录、设备、管道在很多 API 上都能被打开，
     * 但语义完全不同 —— 例如把一个命名管道当配置文件读，会挂在那里等写入端。</p>
     */
    public static Path realFileInside(Path candidate, Path parent) {
        Path real = toRealOrFail(candidate);
        if (!isInside(parent, real) || !Files.isRegularFile(real, LinkOption.NOFOLLOW_LINKS)) {
            throw new WorkspacePathException("文件不在允许范围内，或不是普通文件");
        }
        return real;
    }

    private static Path toRealOrFail(Path candidate) {
        if (candidate == null) {
            throw new WorkspacePathException("路径不能为 null");
        }
        try {
            return candidate.toRealPath();
        } catch (IOException e) {
            // 不存在和无权限在这里合并成同一个结局。区分它们会变成一个
            // 探测工作区外文件是否存在的信道（「不存在」和「没权限」两种回答
            // 本身就是信息）。
            throw new WorkspacePathException("路径无法解析");
        }
    }
}
