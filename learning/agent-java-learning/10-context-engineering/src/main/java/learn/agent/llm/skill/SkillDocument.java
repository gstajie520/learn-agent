package learn.agent.llm.skill;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

import learn.agent.llm.workspace.WorkspaceGuard;

/**
 * 一份解析好的 {@code SKILL.md}：frontmatter 里的元数据 + 分隔符之后的正文。
 *
 * <h3>格式</h3>
 * <pre>
 * ---
 * name: radar-troubleshooting
 * description: 雷达离线时的排查顺序
 * ---
 *
 * 这里开始是正文，只有 load_skill 被调用后才会读到。
 * </pre>
 *
 * <h3>为什么不引 YAML 库，以及这个决定的代价</h3>
 * <p>教材用的是真正的 YAML 解析器。这里手写了一个<b>只认 {@code key: value}</b>
 * 的解析器，理由是本工程只需要两个字符串字段，为它引一个 YAML 依赖不划算。</p>
 *
 * <p><b>但这不是「等价实现」，差异要说清</b>：本解析器比 YAML <b>更严格</b> ——
 * 嵌套结构、多行值、锚点、列表全部会被当成非法而拒绝。这个方向是安全的
 * （fail-closed：看不懂就拒绝，不会误解成别的意思），但如果哪天 frontmatter
 * 需要支持嵌套字段，<b>必须换成真的 YAML 解析器</b>，不能在这里打补丁 ——
 * 手写解析器逐步长出对 YAML 子集的支持，是一条经典的出 bug 路径。</p>
 */
public final class SkillDocument {

    /** 名称规则：小写字母数字，用单个连字符分段。和目录名共用同一条规则。 */
    private static final Pattern NAME_PATTERN =
            Pattern.compile("^[a-z0-9]+(?:-[a-z0-9]+)*$");

    /** 名称长度上限。它要变成路径的一段，所以不能任意长。 */
    public static final int MAX_NAME_LENGTH = 64;

    private final String name;
    private final String description;
    private final String body;

    private SkillDocument(String name, String description, String body) {
        this.name = name;
        this.description = description;
        this.body = body;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    /** @return 分隔符之后的正文；只有显式加载时才会被填充 */
    public String getBody() {
        return body;
    }

    public SkillSummary toSummary() {
        return new SkillSummary(name, description);
    }

    /**
     * 校验一个 Skill 名称。
     *
     * <p>三条规则，全部在<b>碰文件系统之前</b>执行：长度、字符集、保留组件。
     * 名称会成为路径的一段，所以这三条同时是路径安全的第一道关。</p>
     *
     * @throws SkillNameException 任一条不通过
     */
    public static void validateName(String name) {
        if (name == null || name.isEmpty()) {
            throw new SkillNameException("Skill 名称不能为空");
        }
        if (name.length() > MAX_NAME_LENGTH) {
            throw new SkillNameException(
                    "Skill 名称最长 " + MAX_NAME_LENGTH + " 字符，实际 " + name.length());
        }
        if (!NAME_PATTERN.matcher(name).matches()) {
            // 把规则写进错误信息，模型下一轮才改得对。只说「非法」等于让它继续猜。
            throw new SkillNameException(
                    "Skill 名称只允许小写字母、数字和单个连字符：" + name);
        }
        if (WorkspaceGuard.isReservedComponent(name)) {
            throw new SkillNameException("Skill 名称是保留组件：" + name);
        }
    }

    /**
     * 解析一份 {@code SKILL.md} 的文本。
     *
     * <p>{@code bodyExpected} 为 false 时用于扫描阶段 —— 那时只读了 frontmatter，
     * 正文本来就不完整，所以不把它当正文返回，避免调用方误用一段截断的文本。</p>
     *
     * @param text         文件内容（扫描期可能只是 frontmatter 部分）
     * @param bodyExpected 是否把分隔符之后的内容当作正文返回
     * @throws SkillManifestException 格式不合规
     */
    public static SkillDocument parse(String text, boolean bodyExpected) {
        if (text == null) {
            throw new SkillManifestException("SKILL.md 内容为空");
        }
        List<String> lines = splitLines(text);
        if (lines.isEmpty() || !"---".equals(stripEol(lines.get(0)))) {
            throw new SkillManifestException("SKILL.md 必须以 --- 开头的 frontmatter 起始");
        }
        int closing = -1;
        for (int i = 1; i < lines.size(); i++) {
            if ("---".equals(stripEol(lines.get(i)))) {
                closing = i;
                break;
            }
        }
        if (closing < 0) {
            throw new SkillManifestException("SKILL.md 的 frontmatter 没有结束分隔符");
        }

        String name = null;
        String description = null;
        for (int i = 1; i < closing; i++) {
            String line = stripEol(lines.get(i));
            if (line.trim().isEmpty()) {
                continue;
            }
            int colon = line.indexOf(':');
            if (colon <= 0) {
                // 手写解析器的严格边界：看不懂的行一律拒绝，不猜。
                throw new SkillManifestException("frontmatter 只支持 key: value，无法解析：" + line);
            }
            String key = line.substring(0, colon).trim();
            String value = line.substring(colon + 1).trim();
            if ("name".equals(key)) {
                name = value;
            } else if ("description".equals(key)) {
                description = value;
            } else {
                throw new SkillManifestException("frontmatter 出现未知字段：" + key);
            }
        }
        if (name == null || description == null) {
            throw new SkillManifestException("frontmatter 必须同时提供 name 和 description");
        }
        validateName(name);
        if (description.isEmpty()) {
            throw new SkillManifestException("description 不能为空：" + name);
        }

        String body = "";
        if (bodyExpected && closing + 1 < lines.size()) {
            StringBuilder sb = new StringBuilder();
            for (int i = closing + 1; i < lines.size(); i++) {
                sb.append(lines.get(i));
            }
            body = sb.toString();
        }
        return new SkillDocument(name, description, body);
    }

    /** 按 \n 切分但保留行尾，这样拼回正文时不会丢换行风格。 */
    private static List<String> splitLines(String text) {
        List<String> lines = new ArrayList<String>();
        int start = 0;
        for (int i = 0; i < text.length(); i++) {
            if (text.charAt(i) == '\n') {
                lines.add(text.substring(start, i + 1));
                start = i + 1;
            }
        }
        if (start < text.length()) {
            lines.add(text.substring(start));
        }
        return lines;
    }

    /** 去掉行尾的 \n 或 \r\n，让分隔符判断不依赖换行风格。 */
    private static String stripEol(String line) {
        if (line.endsWith("\r\n")) {
            return line.substring(0, line.length() - 2);
        }
        if (line.endsWith("\n")) {
            return line.substring(0, line.length() - 1);
        }
        return line;
    }
}
