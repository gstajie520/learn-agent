package learn.agent.llm.skill;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolRegistry;
import learn.agent.llm.workspace.WorkspacePathException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link SkillRegistry} 的行为测试。
 *
 * <p>本课的全部要点集中在一句话上：<b>目录里只有名称和描述，正文必须显式加载。</b>
 * 下面的断言大半在守这句话的后半句 —— 因为「不小心把正文也暴露了」
 * 不会报错、不会挂测试，只会让系统提示悄悄变长，而那正是这一课要消灭的问题。</p>
 */
public class SkillRegistryTest {

    @TempDir
    Path tempDir;

    /** 场景：20x20，上限 5，cam-01 受保护。Skill 不依赖场景，但工具上下文需要它。 */
    private static ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        return new ToolContext("skill-user", new SceneSnapshot(20, 20, 5, devices,
                Collections.singleton("cam-01")));
    }

    /** 在工作区里造一个 Skill。 */
    private Path writeSkill(String name, String description, String body) throws IOException {
        Path dir = Files.createDirectories(tempDir.resolve("skills").resolve(name));
        String content = "---\nname: " + name + "\ndescription: " + description + "\n---\n" + body;
        Files.write(dir.resolve("SKILL.md"), content.getBytes(StandardCharsets.UTF_8));
        return dir;
    }

    /** 走完整的 prepare/invoke 链路调一次 load_skill，和真实循环里的路径一致。 */
    private ToolExecutionResult invokeLoad(SkillRegistry registry, String rawArguments) {
        ToolRegistry tools = new ToolRegistry();
        tools.register(registry.getToolDefinition());
        PreparedToolCall prepared = tools.prepare(
                new ToolCall("call-1", SkillRegistry.TOOL_NAME, rawArguments));
        if (prepared.isFailed()) {
            return prepared.getError();
        }
        return tools.invoke(prepared, context());
    }

    /**
     * 规则：<b>目录里只有名称和描述，绝不含正文。</b>
     *
     * <p>这是本课存在的理由，也是最容易被无声破坏的一条。哪天有人图省事在
     * {@code SkillSummary} 上加个 {@code body} 字段、或者在 {@code renderCatalog}
     * 里顺手拼上正文，系统提示就会重新变成「一次性塞进去的一大段」——
     * 而这不会报错，只会让每一轮都变贵。</p>
     */
    @Test
    @DisplayName("目录只暴露名称和描述，正文不出现在渲染结果里")
    void shouldExposeCatalogWithoutBodies() throws IOException {
        writeSkill("radar-troubleshooting", "雷达离线时的排查顺序",
                "第一步：确认供电。第二步：看网络。这段正文很长很长。");
        writeSkill("camera-deploy", "摄像头批量部署规范", "正文：先规划点位，再逐台上电。");

        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);
        String rendered = registry.renderCatalog();

        assertEquals(2, registry.getCatalog().size());
        assertTrue(rendered.contains("radar-troubleshooting"), "目录要有名称");
        assertTrue(rendered.contains("雷达离线时的排查顺序"), "目录要有描述");
        // 关键断言：正文一个字都不能出现。
        assertFalse(rendered.contains("确认供电"), "正文泄漏进了目录");
        assertFalse(rendered.contains("先规划点位"), "正文泄漏进了目录");
    }

    /**
     * 规则：只有显式调用 {@code load_skill} 之后才拿到正文。
     *
     * <p>和上一条成对：目录里没有正文，但正文必须真的取得到 ——
     * 否则这个机制就只是「把内容藏起来」，没有完成「按需给出」。</p>
     */
    @Test
    @DisplayName("load_skill 显式调用后返回正文")
    void shouldReturnBodyOnlyAfterExplicitLoad() throws IOException {
        writeSkill("radar-troubleshooting", "雷达离线时的排查顺序", "第一步：确认供电。");

        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);
        ToolExecutionResult result = invokeLoad(registry,
                "{\"name\":\"radar-troubleshooting\"}");

        assertFalse(result.isError(), "合法加载不该失败：" + result.getContent());
        assertTrue(result.getContent().contains("第一步：确认供电"), "应当返回正文");
        // frontmatter 不该混进正文 —— 那两行是元数据，模型已经在目录里见过了。
        assertFalse(result.getContent().contains("description:"),
                "frontmatter 不该出现在正文里");
    }

    /**
     * 规则：扫描阶段<b>不读正文</b>。
     *
     * <p>怎么证明「没读」：造一个 frontmatter 合法、但正文是<b>非法 UTF-8</b> 的文件。
     * 扫描时只读到第二个 {@code ---} 就停，所以碰不到坏字节，扫描应当成功；
     * 而显式加载会读全文，那时才会失败。</p>
     *
     * <p>这条断言的价值在于它区分了「实现成读全文再切分」和「真的只读前半段」——
     * 前者在这个测试里会在扫描阶段就抛异常。</p>
     */
    @Test
    @DisplayName("扫描只读 frontmatter：正文是坏字节时扫描仍成功，加载才失败")
    void shouldReadOnlyFrontmatterDuringScan() throws IOException {
        Path dir = Files.createDirectories(tempDir.resolve("skills").resolve("half-broken"));
        byte[] head = ("---\nname: half-broken\ndescription: 前半合法\n---\n")
                .getBytes(StandardCharsets.UTF_8);
        // 0xFF 0xFE 不是合法 UTF-8 序列。
        byte[] badBody = new byte[] {(byte) 0xFF, (byte) 0xFE, (byte) 0xFF};
        byte[] all = new byte[head.length + badBody.length];
        System.arraycopy(head, 0, all, 0, head.length);
        System.arraycopy(badBody, 0, all, head.length, badBody.length);
        Files.write(dir.resolve("SKILL.md"), all);

        // 扫描成功：证明它没有读到正文那几个坏字节。
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);
        assertEquals(1, registry.getCatalog().size());
        assertEquals("前半合法", registry.getCatalog().get(0).getDescription());

        // 显式加载读全文，这时才撞上坏字节。
        assertThrows(SkillManifestException.class, () -> registry.loadSkill("half-broken"));
    }

    /**
     * 规则：目录不存在时返回<b>空注册表</b>，不抛异常。
     *
     * <p>「这个工作区没配 Skill」是完全正常的状态。抛异常会让所有不用 Skill 的
     * 场景都得先建一个空目录才能启动。</p>
     */
    @Test
    @DisplayName("没有 skills 目录：空目录，不是错误")
    void shouldReturnEmptyCatalogWhenDirectoryAbsent() {
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);

        assertTrue(registry.getCatalog().isEmpty());
        assertEquals("", registry.renderCatalog(), "空目录渲染成空串，不加占位文字");
        assertTrue(registry.getNames().isEmpty());
    }

    /**
     * 规则：条目数预算生效，且<b>按名称排序后截断</b>。
     *
     * <p>排序这一点不能省：如果按文件系统枚举顺序截断，同一份工作区在不同机器上
     * 留下的条目就不一样 —— 于是「模型能用哪几个 Skill」取决于部署在哪台机器上，
     * 而这种差异从日志里完全看不出来。</p>
     */
    @Test
    @DisplayName("条目数预算：超出部分截断，且截断结果与机器无关")
    void shouldRespectEntryBudgetDeterministically() throws IOException {
        writeSkill("aaa-first", "第一个", "正文");
        writeSkill("bbb-second", "第二个", "正文");
        writeSkill("ccc-third", "第三个", "正文");

        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(),
                new SkillScanOptions(null, 2, SkillScanOptions.DEFAULT_MAX_BYTES));

        assertEquals(2, registry.getCatalog().size());
        // 按名称排序，所以留下的必然是前两个，和目录枚举顺序无关。
        assertEquals("aaa-first", registry.getCatalog().get(0).getName());
        assertEquals("bbb-second", registry.getCatalog().get(1).getName());
        // 被截断的那个仍然可以加载 —— 预算限制的是目录，不是能力。
        assertEquals("正文", registry.loadSkill("ccc-third").trim());
    }

    /**
     * 规则：字节预算按 UTF-8 计量，且<b>只整条列出，绝不列一半</b>。
     *
     * <p>列半行的后果是模型看到一个残缺的名字，然后拿它去调 {@code load_skill} ——
     * 那必然失败，而且失败原因它看不懂（它以为自己抄对了）。</p>
     *
     * <p>中文描述在这里是关键：一个汉字 3 字节，如果按字符数算预算就会严重超标。</p>
     */
    @Test
    @DisplayName("字节预算：按 UTF-8 计量，不产生残缺条目")
    void shouldCountUtf8BytesAndNeverEmitPartialEntry() throws IOException {
        writeSkill("aaa", "短", "正文");
        // 这条描述是中文，UTF-8 下每字 3 字节，很容易撑爆预算。
        writeSkill("bbb", "这是一条相当长的中文描述用来把字节预算撑爆", "正文");

        // 预算只够第一条。
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(),
                new SkillScanOptions(null, 100, 20));
        String rendered = registry.renderCatalog();

        assertEquals(1, registry.getCatalog().size(), "预算只够一条");
        assertEquals("aaa", registry.getCatalog().get(0).getName());
        // 渲染结果的实际字节数不能超预算。
        assertTrue(rendered.getBytes(StandardCharsets.UTF_8).length <= 20,
                "渲染结果超出了字节预算：" + rendered.getBytes(StandardCharsets.UTF_8).length);
        // 第二条要么完整出现，要么完全不出现，不能出现片段。
        assertFalse(rendered.contains("这是一条"), "出现了被截断的条目片段");
    }

    /** 规则：预算参数必须为正数，0 和负数在构造期就拒绝。 */
    @Test
    @DisplayName("预算参数：必须为正数")
    void shouldRejectNonPositiveBudgets() {
        assertThrows(IllegalArgumentException.class,
                () -> new SkillScanOptions(null, 0, 100));
        assertThrows(IllegalArgumentException.class,
                () -> new SkillScanOptions(null, 10, -1));
    }

    /**
     * 规则：两个 Skill 同名 → <b>扫描期硬失败</b>，不允许后来者覆盖。
     *
     * <p>违反会怎样：往工作区里塞一个同名 Skill 就能<b>替换掉</b>一个已有能力的正文，
     * 而模型看到的目录条目一字未变。允许覆盖等于允许静默替换。</p>
     *
     * <p>这里用两个不同目录声明同一个 name 来构造冲突。注意「name 必须等于目录名」
     * 那条规则会先拦下其中一个 —— 所以这个测试实际验证的是<b>两条规则至少有一条生效</b>，
     * 两者都会阻止静默覆盖。</p>
     */
    @Test
    @DisplayName("同名 Skill：扫描期失败，不静默覆盖")
    void shouldRejectDuplicateNames() throws IOException {
        writeSkill("alpha", "第一个", "正文 A");
        // 第二个目录叫 beta，却声称自己是 alpha。
        Path dir = Files.createDirectories(tempDir.resolve("skills").resolve("beta"));
        Files.write(dir.resolve("SKILL.md"),
                "---\nname: alpha\ndescription: 冒充的\n---\n正文 B"
                        .getBytes(StandardCharsets.UTF_8));

        SkillException e = assertThrows(SkillException.class,
                () -> SkillRegistry.scan(tempDir.toString(), null));
        // 不管是撞名还是名不符目录，都必须失败而不是选一个生效。
        assertTrue(e instanceof DuplicateSkillException || e instanceof SkillManifestException,
                "应当是撞名或名称不符，实际：" + e.getClass().getSimpleName());
    }

    /**
     * 规则：frontmatter 声明的 name 必须和目录名一致。
     *
     * <p>违反会怎样：一个叫 {@code deploy-guide} 的目录可以声明自己是
     * {@code safe-readonly-guide}。模型以为加载的是后者，实际读到的是前者的正文 ——
     * 这是<b>身份冒充</b>。</p>
     */
    @Test
    @DisplayName("name 与目录名不一致：拒绝（防身份冒充）")
    void shouldRequireNameToMatchDirectory() throws IOException {
        Path dir = Files.createDirectories(tempDir.resolve("skills").resolve("deploy-guide"));
        Files.write(dir.resolve("SKILL.md"),
                "---\nname: safe-readonly-guide\ndescription: 冒充\n---\n危险正文"
                        .getBytes(StandardCharsets.UTF_8));

        assertThrows(SkillManifestException.class,
                () -> SkillRegistry.scan(tempDir.toString(), null));
    }

    /**
     * 规则：坏参数在<b>碰文件系统之前</b>就被挡下。
     *
     * <p>顺序是硬性的：名字先过规则，才有资格变成路径的一段。反过来的话，
     * {@code ../../etc/passwd} 已经被拼进一个真实 Path 对象了，只是碰巧还没读 ——
     * 而「碰巧」不是安全边界。</p>
     *
     * <p>四类都要拦：路径穿越、保留设备名、未知字段、缺字段。</p>
     */
    @Test
    @DisplayName("坏参数：穿越、保留名、未知字段、缺字段全部在读文件前拦下")
    void shouldRejectBadArgumentsBeforeFileAccess() throws IOException {
        writeSkill("radar-troubleshooting", "描述", "正文");
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);

        // 路径穿越：名字规则不允许斜杠和点，所以这里连 Path 都构造不出来。
        ToolExecutionResult traversal = invokeLoad(registry, "{\"name\":\"../../etc/passwd\"}");
        assertTrue(traversal.isError());
        assertEquals("invalid_arguments", traversal.getErrorCode());

        // Windows 保留设备名。
        ToolExecutionResult reserved = invokeLoad(registry, "{\"name\":\"con\"}");
        assertTrue(reserved.isError());
        assertEquals("invalid_arguments", reserved.getErrorCode());

        // 未知字段：和第 1 课 todo_write 同一条规则，静默忽略会让模型以为被接受了。
        ToolExecutionResult extra = invokeLoad(registry,
                "{\"name\":\"radar-troubleshooting\",\"verbose\":true}");
        assertTrue(extra.isError());
        assertEquals("invalid_arguments", extra.getErrorCode());
        assertTrue(extra.getContent().contains("verbose"), "错误信息要点出多余字段名");

        // 缺字段。
        ToolExecutionResult missing = invokeLoad(registry, "{}");
        assertTrue(missing.isError());
        assertEquals("invalid_arguments", missing.getErrorCode());
    }

    /**
     * 规则：名字合法但没注册 → {@code skill_not_found}，且错误信息<b>不含真实路径</b>。
     *
     * <p>路径信息对模型没用，但对攻击者有用：逐个试名字、根据错误码的差别
     * 就能反推目录结构。</p>
     */
    @Test
    @DisplayName("未注册的名字：skill_not_found，且不泄漏路径")
    void shouldReportNotFoundWithoutLeakingPaths() throws IOException {
        writeSkill("alpha", "描述", "正文");
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);

        ToolExecutionResult result = invokeLoad(registry, "{\"name\":\"nonexistent\"}");

        assertTrue(result.isError());
        assertEquals("skill_not_found", result.getErrorCode());
        assertFalse(result.getContent().contains(tempDir.toString()),
                "错误信息里出现了真实路径：" + result.getContent());
    }

    /**
     * 规则：<b>加载时重新解析真实路径</b> —— 扫描通过不代表加载时还安全（TOCTOU）。
     *
     * <p>这是本课最容易被简化掉的一条。做法是：扫描完成后，把 Skill 目录换成
     * 一个指向工作区外的符号链接，然后加载。如果实现信任了扫描期的结果，
     * 这次加载会读到工作区外的文件。</p>
     *
     * <p>违反会怎样：攻击者（或一个恰好在同步文件的进程）只要在扫描和加载之间的
     * 窗口里替换目录，就能让 Agent 读出任意文件的内容 —— 而模型会把它当作
     * 一份正常的操作规范来执行。</p>
     */
    @Test
    @DisplayName("加载时重查路径：扫描后目录被换成越界链接，加载必须失败")
    void shouldRecheckPathOnLoadAfterDirectorySwapped() throws IOException {
        writeSkill("swappable", "描述", "原始正文");
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);
        // 扫描时一切正常。
        assertEquals("原始正文", registry.loadSkill("swappable").trim());

        // 现在把这个目录换成指向工作区外的链接。
        Path outside = Files.createDirectory(tempDir.getParent()
                .resolve("outside-" + System.nanoTime()));
        Files.write(outside.resolve("SKILL.md"),
                "---\nname: swappable\ndescription: 冒充\n---\n工作区外的内容"
                        .getBytes(StandardCharsets.UTF_8));
        Path skillDir = tempDir.resolve("skills").resolve("swappable");
        try {
            deleteRecursively(skillDir);
            Files.createSymbolicLink(skillDir, outside);
        } catch (IOException | UnsupportedOperationException e) {
            System.out.println("跳过 TOCTOU 测试：本机无法创建符号链接（"
                    + e.getClass().getSimpleName() + "）");
            return;
        }

        // 加载必须失败：真实路径已经在工作区外了。
        assertThrows(WorkspacePathException.class, () -> registry.loadSkill("swappable"));

        // 走工具链路时翻译成稳定错误码，而不是把异常抛给模型。
        ToolExecutionResult result = invokeLoad(registry, "{\"name\":\"swappable\"}");
        assertTrue(result.isError());
        assertEquals("skill_path_escape", result.getErrorCode());
        assertFalse(result.getContent().contains("工作区外的内容"),
                "越界内容泄漏给了模型");
    }

    /** 规则：{@code load_skill} 是 READ，不该触发确认流程。 */
    @Test
    @DisplayName("副作用等级：READ，不需要人工确认")
    void shouldDeclareReadEffect() {
        SkillRegistry registry = SkillRegistry.scan(tempDir.toString(), null);

        assertEquals(ToolEffect.READ, registry.getToolDefinition().getEffect());
        assertFalse(registry.getToolDefinition().getEffect().requiresConfirmation(),
                "查阅文档天天弹确认框，用户会把整个机制关掉");
    }

    /**
     * 规则：frontmatter 格式不合规一律拒绝，且<b>比 YAML 更严</b>。
     *
     * <p>手写解析器只认 {@code key: value}。这个方向是安全的（看不懂就拒绝，
     * 不会误解成别的意思），但必须有测试钉住「严格」这件事本身 ——
     * 否则将来有人为了兼容某个写法放宽它，就会一步步长成一个半成品 YAML 解析器。</p>
     */
    @Test
    @DisplayName("frontmatter 不合规：缺分隔符、缺字段、未知字段全部拒绝")
    void shouldRejectMalformedFrontmatter() throws IOException {
        Path base = Files.createDirectories(tempDir.resolve("skills"));

        // 没有 frontmatter 起始分隔符。
        Path noStart = Files.createDirectories(base.resolve("no-start"));
        Files.write(noStart.resolve("SKILL.md"),
                "name: no-start\n".getBytes(StandardCharsets.UTF_8));
        assertThrows(SkillManifestException.class,
                () -> SkillRegistry.scan(tempDir.toString(), null));
        deleteRecursively(noStart);

        // 缺 description。
        Path noDesc = Files.createDirectories(base.resolve("no-desc"));
        Files.write(noDesc.resolve("SKILL.md"),
                "---\nname: no-desc\n---\n正文".getBytes(StandardCharsets.UTF_8));
        assertThrows(SkillManifestException.class,
                () -> SkillRegistry.scan(tempDir.toString(), null));
        deleteRecursively(noDesc);

        // 未知字段。
        Path unknown = Files.createDirectories(base.resolve("unknown-field"));
        Files.write(unknown.resolve("SKILL.md"),
                "---\nname: unknown-field\ndescription: d\nauthor: x\n---\n正文"
                        .getBytes(StandardCharsets.UTF_8));
        assertThrows(SkillManifestException.class,
                () -> SkillRegistry.scan(tempDir.toString(), null));
    }

    private static void deleteRecursively(Path path) throws IOException {
        if (!Files.exists(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            return;
        }
        if (Files.isDirectory(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            try (java.util.stream.Stream<Path> children = Files.list(path)) {
                for (Path child : children.toArray(Path[]::new)) {
                    deleteRecursively(child);
                }
            }
        }
        Files.delete(path);
    }
}
