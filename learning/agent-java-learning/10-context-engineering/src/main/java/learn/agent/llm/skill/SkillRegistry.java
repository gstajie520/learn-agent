package learn.agent.llm.skill;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.structured.ValidationResult;
import learn.agent.llm.tool.ToolArgumentValidator;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.workspace.WorkspaceGuard;
import learn.agent.llm.workspace.WorkspacePathException;

/**
 * Skill 注册表：把「一大段指令」拆成<b>目录</b>和<b>正文</b>两段。
 *
 * <h3>这一课解决什么</h3>
 * <p>前两课（会话计划、子 Agent）解决的是「别忘了目标」和「别把探索过程堆进主对话」。
 * 但还有第三种上下文膨胀：<b>为了让 Agent 会做某件事，把大段操作规范塞进系统提示。</b>
 * 十个领域各一份规范，系统提示就上万 token —— 而任何一次对话通常只用到其中一份，
 * 剩下九份每一轮都在付费，还稀释了模型对当前任务的注意力。</p>
 *
 * <p>本课的机制是两段式：</p>
 * <pre>
 * 系统提示里只放目录（每条一行）        ← 便宜，常驻
 *   - radar-troubleshooting: 雷达离线时的排查顺序
 *   - camera-deploy: 摄像头批量部署规范
 *         │
 *         │  模型判断这次要用哪一份
 *         ▼
 * load_skill(name="radar-troubleshooting")   ← 贵，按需
 *   → 返回那一份的完整正文
 * </pre>
 *
 * <p>关键在于<b>扫描阶段只读 frontmatter，不读正文</b>。一百个 Skill 的目录
 * 只解码一百段 frontmatter，正文一个字节都不碰。这不是优化，是这个设计成立的前提 ——
 * 如果扫描就把正文全读进内存，那和塞进系统提示的区别只剩「暂时没发出去」。</p>
 *
 * <h3>和阶段 10 的 RAG 是两条路</h3>
 * <p>都在回答「上下文放不下全部知识怎么办」。Skill 是<b>少拿</b>：知识在本地、
 * 边界清楚、按名字精确取，取到的是完整一份。RAG 是<b>去找</b>：知识在外部、
 * 按语义相似度召回，取到的是若干片段。前者适合「操作规范」这种必须完整、
 * 不能只给片段的内容；后者适合「资料库」这种没法预先命名的内容。</p>
 *
 * <h3>安全边界（本工程第一次引入文件访问）</h3>
 * <p>Skill 名会成为路径的一段，而名字来自<b>模型</b>。所以校验顺序是硬性的：
 * <b>先验证名字，再拼路径，最后加载时重新解析真实路径</b>。
 * 三步的理由分别见 {@link SkillNameException}、{@link WorkspaceGuard#resolveRelative}
 * 和 {@link WorkspaceGuard#realDirectoryInside}。</p>
 */
public final class SkillRegistry {

    /** 工具名。 */
    public static final String TOOL_NAME = "load_skill";

    /** 扫描期记录的一条 Skill。正文<b>不在</b>这里 —— 那是本课的全部要点。 */
    private static final class SkillRecord {
        final String name;
        final String description;
        final String directoryName;
        final Path directoryPath;
        final Path manifestPath;

        SkillRecord(String name, String description, String directoryName,
                    Path directoryPath, Path manifestPath) {
            this.name = name;
            this.description = description;
            this.directoryName = directoryName;
            this.directoryPath = directoryPath;
            this.manifestPath = manifestPath;
        }
    }

    private final WorkspaceGuard workspace;
    private final Path skillsRoot;
    private final Map<String, SkillRecord> records;
    private final List<SkillSummary> catalog;
    private final ToolDefinition toolDefinition;

    private SkillRegistry(WorkspaceGuard workspace, Path skillsRoot,
                          Map<String, SkillRecord> records, List<SkillSummary> catalog) {
        this.workspace = workspace;
        this.skillsRoot = skillsRoot;
        this.records = Collections.unmodifiableMap(records);
        this.catalog = Collections.unmodifiableList(catalog);
        this.toolDefinition = buildToolDefinition();
    }

    /**
     * 扫描工作区，建立一个<b>不可变快照</b>。
     *
     * <p>目录不存在时返回<b>空注册表而不是抛异常</b>：「这个工作区没配 Skill」
     * 是完全正常的状态，不是错误。抛异常会让所有不用 Skill 的场景都得先建个空目录。</p>
     *
     * @param workspaceRoot 工作区路径
     * @param options       预算配置，null 取默认
     * @throws DuplicateSkillException 两个 Skill 同名（部署错误，扫描期硬失败）
     * @throws SkillManifestException  某个 SKILL.md 不合规
     */
    public static SkillRegistry scan(String workspaceRoot, SkillScanOptions options) {
        SkillScanOptions effective = options == null ? SkillScanOptions.defaults() : options;
        WorkspaceGuard guard = WorkspaceGuard.open(workspaceRoot);

        // 词法关：Skill 根必须是工作区内的相对目录。
        Path lexicalRoot = guard.resolveRelative(effective.getSkillsDirectory());
        if (!Files.exists(lexicalRoot, LinkOption.NOFOLLOW_LINKS)) {
            return new SkillRegistry(guard, lexicalRoot,
                    new LinkedHashMap<String, SkillRecord>(), new ArrayList<SkillSummary>());
        }
        // 物理关：解析真实路径，确认没被链接指到区外。
        Path realRoot = WorkspaceGuard.realDirectoryInside(lexicalRoot, guard.getRoot());

        // 用 TreeMap 让扫描结果与文件系统的枚举顺序无关 —— 否则同一份工作区
        // 在不同机器上目录顺序不同，catalog 被预算截断时留下的条目也不同。
        Map<String, SkillRecord> byName = new TreeMap<String, SkillRecord>();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(realRoot)) {
            for (Path entry : entries) {
                SkillRecord record = readRecord(entry, realRoot);
                if (record == null) {
                    continue;
                }
                if (byName.containsKey(record.name)) {
                    throw new DuplicateSkillException("Skill 名称重复：" + record.name);
                }
                byName.put(record.name, record);
            }
        } catch (IOException e) {
            throw new SkillException("无法枚举 Skill 目录：" + e.getMessage());
        }

        List<SkillSummary> bounded = boundedCatalog(byName.values(),
                effective.getMaxEntries(), effective.getMaxBytes());
        return new SkillRegistry(guard, realRoot,
                new LinkedHashMap<String, SkillRecord>(byName), bounded);
    }

    /** 读一个候选目录。不是 Skill 目录（没有 SKILL.md）时返回 null，不算错误。 */
    private static SkillRecord readRecord(Path entry, Path realRoot) {
        String directoryName = entry.getFileName().toString();
        // 目录名先过名称规则：它同时是路径的一段和模型将来要填的名字。
        // 不合规的目录直接跳过而不是报错 —— 工作区里可能有别的东西。
        try {
            SkillDocument.validateName(directoryName);
        } catch (SkillNameException e) {
            return null;
        }
        Path directory;
        try {
            directory = WorkspaceGuard.realDirectoryInside(entry, realRoot);
        } catch (WorkspacePathException e) {
            // 目录被链接指到了 Skill 根之外。跳过而不是让整次扫描失败：
            // 一个坏目录不该让其他 Skill 全都用不了。
            return null;
        }
        Path lexicalManifest = directory.resolve("SKILL.md");
        if (!Files.exists(lexicalManifest, LinkOption.NOFOLLOW_LINKS)) {
            return null;
        }
        Path manifest = WorkspaceGuard.realFileInside(lexicalManifest, directory);

        // 只读 frontmatter，不读正文 —— 这是两段式设计成立的前提。
        String frontmatter = readFrontmatterOnly(manifest);
        SkillDocument document = SkillDocument.parse(frontmatter, false);

        // manifest 声明的名字必须和目录名一致，否则是身份冒充，见 SkillManifestException。
        if (!document.getName().equals(directoryName)) {
            throw new SkillManifestException(
                    "SKILL.md 声明的 name 与目录名不一致：目录 " + directoryName
                            + "，声明 " + document.getName());
        }
        return new SkillRecord(document.getName(), document.getDescription(),
                directoryName, entry, entry.resolve("SKILL.md"));
    }

    /**
     * 按双预算截断目录。
     *
     * <p><b>只整条列出，绝不列一半。</b>字节预算是按「整条渲染文本」算的，
     * 放不下就整条不放。列半行的后果是模型看到一个残缺的名字，
     * 然后拿它去调 {@code load_skill} —— 那必然失败，而且失败原因它看不懂。</p>
     */
    private static List<SkillSummary> boundedCatalog(Iterable<SkillRecord> ordered,
                                                     int maxEntries, int maxBytes) {
        List<SkillSummary> result = new ArrayList<SkillSummary>();
        int usedBytes = 0;
        for (SkillRecord record : ordered) {
            if (result.size() >= maxEntries) {
                break;
            }
            String line = renderLine(record.name, record.description);
            // 第一条不需要前导换行，后面每条都要 —— 预算要算上那个换行符，
            // 否则「刚好卡在边界」时实际输出会超预算。
            int separator = result.isEmpty() ? 0 : 1;
            int entryBytes = line.getBytes(StandardCharsets.UTF_8).length + separator;
            if (usedBytes + entryBytes > maxBytes) {
                break;
            }
            result.add(new SkillSummary(record.name, record.description));
            usedBytes += entryBytes;
        }
        return result;
    }

    private static String renderLine(String name, String description) {
        return "- " + name + "：" + description;
    }

    /**
     * 只读到 frontmatter 的结束分隔符，<b>不读正文</b>。
     *
     * <p>这个方法是两段式设计的物理实现。分块读、遇到第二个 {@code ---} 立刻返回 ——
     * 一个 10 MB 的 SKILL.md 在扫描阶段只会被读掉前几百字节。</p>
     *
     * <p>如果这里图省事写成 {@code Files.readAllBytes} 再切分，那么「扫描不读正文」
     * 就成了一句空话：正文已经进了内存，只是没拼进 prompt 而已。100 个 Skill
     * 各 1 MB，启动时就是 100 MB 的无用读取。</p>
     */
    private static String readFrontmatterOnly(Path manifest) {
        StringBuilder collected = new StringBuilder();
        int separatorsSeen = 0;
        try (InputStream in = Files.newInputStream(manifest)) {
            byte[] chunk = new byte[4096];
            int read;
            // carry 存放上一块末尾那个还没遇到换行的残行，跨块拼接用。
            byte[] carry = new byte[0];
            while ((read = in.read(chunk)) > 0) {
                byte[] combined = new byte[carry.length + read];
                System.arraycopy(carry, 0, combined, 0, carry.length);
                System.arraycopy(chunk, 0, combined, carry.length, read);
                int start = 0;
                for (int i = 0; i < combined.length; i++) {
                    if (combined[i] != '\n') {
                        continue;
                    }
                    byte[] line = new byte[i - start + 1];
                    System.arraycopy(combined, start, line, 0, line.length);
                    start = i + 1;
                    collected.append(decodeUtf8Strict(line, manifest));
                    if (isSeparatorLine(line)) {
                        separatorsSeen++;
                        if (separatorsSeen >= 2) {
                            return collected.toString();
                        }
                    }
                }
                carry = new byte[combined.length - start];
                System.arraycopy(combined, start, carry, 0, carry.length);
            }
            if (carry.length > 0) {
                collected.append(decodeUtf8Strict(carry, manifest));
            }
            // 没有第二个分隔符也照样返回，让 SkillDocument.parse 报「缺结束分隔符」——
            // 那个错误信息比这里能给的更准确。
            return collected.toString();
        } catch (IOException e) {
            throw new SkillException("无法读取 SKILL.md：" + e.getMessage());
        }
    }

    /** 恰好三个连字符的一行才算分隔符，兼容 CRLF。 */
    private static boolean isSeparatorLine(byte[] line) {
        int end = line.length;
        if (end > 0 && line[end - 1] == '\n') {
            end--;
        }
        if (end > 0 && line[end - 1] == '\r') {
            end--;
        }
        return end == 3 && line[0] == '-' && line[1] == '-' && line[2] == '-';
    }

    /**
     * 严格 UTF-8 解码：非法字节<b>报错而不是替换成 U+FFFD</b>。
     *
     * <p>默认的宽松解码会把坏字节变成 `?`，于是一个二进制文件也能「成功」解析出
     * 一堆问号，然后被当成正文塞给模型。宁可明确失败。</p>
     */
    private static String decodeUtf8Strict(byte[] bytes, Path source) {
        CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT);
        try {
            CharBuffer decoded = decoder.decode(ByteBuffer.wrap(bytes));
            return decoded.toString();
        } catch (CharacterCodingException e) {
            throw new SkillManifestException("SKILL.md 不是合法 UTF-8");
        }
    }

    /** @return 已受预算约束的目录快照，永远不含正文 */
    public List<SkillSummary> getCatalog() {
        return catalog;
    }

    /** @return 全部已注册的名称，按字典序 */
    public List<String> getNames() {
        return Collections.unmodifiableList(new ArrayList<String>(records.keySet()));
    }

    public ToolDefinition getToolDefinition() {
        return toolDefinition;
    }

    /**
     * 渲染成能直接拼进系统提示的文本。
     *
     * <p>没有任何 Skill 时返回空串，<b>不返回「（无）」这类占位</b> ——
     * 那会让系统提示里多出一段没有信息量的话。调用方自己决定要不要写标题。</p>
     */
    public String renderCatalog() {
        StringBuilder sb = new StringBuilder();
        for (SkillSummary entry : catalog) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append(renderLine(entry.getName(), entry.getDescription()));
        }
        return sb.toString();
    }

    /**
     * 按名称加载正文。
     *
     * <p><b>这里会把扫描期做过的路径检查全部重做一遍</b>，一层都不省：
     * Skill 根、Skill 目录、manifest 文件，三层各自重新解析真实路径。</p>
     *
     * <p>为什么不能信任扫描期的结果：扫描和加载之间隔着任意长的时间。
     * 这段时间里目录可以被换成一个指向工作区外的链接（TOCTOU）。
     * 存下来的「已验证路径」在那一刻就过期了。</p>
     *
     * <p>还要重新核对一遍「manifest 里的 name == 目录名」。因为 SKILL.md 的内容
     * 也可能在扫描之后被替换 —— 换成一个声称自己叫别的名字的文件。
     * 只查路径不查内容，等于防住了目录被换、没防住文件被换。</p>
     *
     * @throws SkillNotFoundException  名字合法但没注册
     * @throws SkillNameException      名字本身不合法
     * @throws WorkspacePathException  路径已经不再安全
     * @throws SkillManifestException  manifest 变得不合规了
     */
    public String loadSkill(String name) {
        SkillDocument.validateName(name);
        SkillRecord record = records.get(name);
        if (record == null) {
            throw new SkillNotFoundException("没有注册名为 " + name + " 的 Skill");
        }
        // 三层全部重新解析，顺序从外到内 —— 外层不可信时内层的结果没有意义。
        Path currentRoot = WorkspaceGuard.realDirectoryInside(skillsRoot, workspace.getRoot());
        Path currentDirectory = WorkspaceGuard.realDirectoryInside(record.directoryPath, currentRoot);
        Path currentManifest = WorkspaceGuard.realFileInside(
                currentDirectory.resolve("SKILL.md"), currentDirectory);

        String text;
        try {
            text = decodeUtf8Strict(Files.readAllBytes(currentManifest), currentManifest);
        } catch (IOException e) {
            throw new SkillException("无法读取 Skill 正文：" + e.getMessage());
        }
        SkillDocument document = SkillDocument.parse(text, true);
        if (!document.getName().equals(record.name)
                || !document.getName().equals(record.directoryName)) {
            throw new SkillManifestException("SKILL.md 的 name 与目录名不再一致：" + name);
        }
        return document.getBody();
    }

    /** {@code load_skill} 的参数 Schema。只有一个字段，刻意不给别的。 */
    private static String buildParametersSchema() {
        return "{"
                + "\"type\":\"object\","
                + "\"properties\":{"
                + "\"name\":{"
                + "\"type\":\"string\","
                + "\"description\":\"目录里列出的 Skill 名称，必须原样填写。\""
                + "}"
                + "},"
                + "\"required\":[\"name\"]"
                + "}";
    }

    /**
     * 组装工具定义。
     *
     * <p><b>副作用等级是 READ。</b>它只读文件、不改任何状态，撤销成本为零。
     * 标成 WRITE 或 DESTRUCTIVE 会让它触发确认流程 —— 一个「查阅文档」的动作
     * 天天弹确认框，用户会直接把整个机制关掉。</p>
     */
    private ToolDefinition buildToolDefinition() {
        return new ToolDefinition(TOOL_NAME,
                "加载目录中某一个 Skill 的完整正文。只有目录里列出的名称可用。",
                buildParametersSchema(),
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return handleLoad(arguments, context);
                    }
                },
                new ToolArgumentValidator() {
                    @Override
                    public ValidationResult<JsonNode> validate(JsonNode arguments) {
                        return validateArguments(arguments);
                    }
                });
    }

    /**
     * 参数校验，在<b>碰文件系统之前</b>跑。
     *
     * <p>顺序很重要：名字先过规则，才有资格变成路径的一段。反过来的话，
     * {@code ../../etc/passwd} 已经被拼进一个真实 Path 对象了，只是碰巧还没读。</p>
     */
    private static ValidationResult<JsonNode> validateArguments(JsonNode arguments) {
        if (arguments == null) {
            return ValidationResult.fail("参数不能为 null");
        }
        JsonNode name = arguments.get("name");
        if (name == null || !name.isTextual()) {
            return ValidationResult.fail("缺少 name 字段（字符串）");
        }
        // 未知字段一律拒绝，和第 1 课 todo_write 同一条规则：
        // 静默忽略多余字段会让模型以为它们被接受了。
        List<String> unknown = new ArrayList<String>();
        java.util.Iterator<String> fields = arguments.fieldNames();
        while (fields.hasNext()) {
            String field = fields.next();
            if (!"name".equals(field)) {
                unknown.add(field);
            }
        }
        if (!unknown.isEmpty()) {
            return ValidationResult.fail("不认识的字段：" + unknown + "；load_skill 只接受 name");
        }
        try {
            SkillDocument.validateName(name.asText());
        } catch (SkillNameException e) {
            return ValidationResult.fail(e.getMessage());
        }
        return ValidationResult.ok(arguments);
    }

    /**
     * handler：把领域异常翻译成稳定的工具错误码。
     *
     * <p>错误码全部是短标识，且<b>不含任何真实路径</b>。路径信息对模型没用，
     * 但对攻击者有用 —— 逐个试名字、根据「路径不安全」和「不存在」的差别，
     * 就能反推出目录结构。</p>
     *
     * <h3>如实记下的一条缺口：没有工作区归属校验</h3>
     * <p>教材在这里多做一件事：解析 {@code ToolContext.workspace}，确认它和注册表
     * 扫描时用的工作区是同一个，不一致就返回 {@code skill_workspace_mismatch}。
     * 它防的是「拿 A 工作区的注册表去服务 B 工作区的会话」。</p>
     *
     * <p><b>Java 侧做不了这个检查</b>，因为域重映射之后 {@code ToolContext} 携带的是
     * {@code identity} 和 {@code SceneSnapshot}，<b>没有</b> workspace 字段 ——
     * 没有可比对的东西。当前工程里注册表与工作区是构造期绑定的，
     * 单会话下不会错配；但如果将来把它用在多租户场景，
     * 「注册表属于哪个工作区」这件事就必须有一个运行期可校验的载体。
     * 这条差异记在这里，不假装已经防住了。</p>
     */
    private ToolExecutionResult handleLoad(JsonNode arguments, ToolContext context) {
        if (context == null) {
            // 这是编程错误，不是模型的错，按本工程既有约定抛异常。
            throw new IllegalArgumentException("context 不能为 null");
        }
        String name = arguments.get("name").asText();
        try {
            return ToolExecutionResult.success(loadSkill(name));
        } catch (SkillNotFoundException e) {
            return ToolExecutionResult.error("skill_not_found",
                    "目录里没有这个 Skill；请从系统提示列出的名称中选一个");
        } catch (SkillNameException e) {
            return ToolExecutionResult.error("invalid_arguments", e.getMessage());
        } catch (WorkspacePathException e) {
            return ToolExecutionResult.error("skill_path_escape",
                    "这个 Skill 的路径已不再安全，无法加载");
        } catch (SkillManifestException e) {
            return ToolExecutionResult.error("invalid_skill",
                    "这个 Skill 的定义文件不合规，换一个");
        } catch (SkillException e) {
            return ToolExecutionResult.error("skill_load_error", "Skill 加载失败");
        }
    }
}
