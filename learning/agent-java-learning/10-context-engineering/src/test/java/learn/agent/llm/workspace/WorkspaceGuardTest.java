package learn.agent.llm.workspace;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link WorkspaceGuard} 的边界测试。
 *
 * <p>这是本工程第一次引入文件访问，所以这个测试类的地位和别处不同：
 * 它守的不是「功能对不对」，而是<b>「模型给的字符串能不能跑到工作区外面去」</b>。
 * 每一条断言都对应一种真实的逃逸手法。</p>
 *
 * <p>后面第 4 课（产物落盘）和第 5 课（文件记忆）都会复用这一层，
 * 所以这里漏掉的每一条，都会在后两课里变成同样的洞。</p>
 */
public class WorkspaceGuardTest {

    @TempDir
    Path tempDir;

    /** 规则：正常的相对路径能拼出工作区内的绝对路径。 */
    @Test
    @DisplayName("正常相对路径：拼进工作区内")
    void shouldResolveNormalRelativePath() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());
        Path resolved = guard.resolveRelative("skills/demo");

        assertTrue(resolved.isAbsolute(), "结果必须是绝对路径");
        assertTrue(WorkspaceGuard.isInside(guard.getRoot(), resolved),
                "结果必须落在工作区内");
        assertTrue(resolved.endsWith(Path.of("skills", "demo")));
    }

    /**
     * 规则：{@code ..} 组件一律拒绝。
     *
     * <p>违反会怎样：模型返回 {@code ../../.ssh/id_rsa} 就能读到工作区外的私钥。
     * 这不需要模型「怀有恶意」—— 提示词注入、或者它只是把相对路径算错了，
     * 都会走到同一个地方。</p>
     */
    @Test
    @DisplayName("父级穿越：三种写法全部拒绝")
    void shouldRejectParentTraversal() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("../secret"));
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("a/../../secret"));
        // 结尾的 .. 同样要拒 —— 它把目标指向父目录本身。
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("skills/.."));
    }

    /**
     * 规则：含 {@code ..} 子串但不是独立组件的文件名<b>要放行</b>。
     *
     * <p>和上一条成对。用 {@code contains("..")} 判断会把这些合法名字全毙掉，
     * 那样闸门就从安全措施退化成了功能残废 —— 而这类误伤最难被发现，
     * 因为它表现为「某些文件莫名其妙读不了」。</p>
     */
    @Test
    @DisplayName("含 .. 子串的合法文件名：放行，不误伤")
    void shouldAllowNamesContainingDoubleDots() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        assertTrue(WorkspaceGuard.isInside(guard.getRoot(),
                guard.resolveRelative("my..file.txt")));
        assertTrue(WorkspaceGuard.isInside(guard.getRoot(),
                guard.resolveRelative("..hidden")));
        assertTrue(WorkspaceGuard.isInside(guard.getRoot(),
                guard.resolveRelative("a/foo..bar/b")));
    }

    /**
     * 规则：绝对路径的四种形态全部拒绝。
     *
     * <p>违反会怎样：{@code Path.resolve} 遇到绝对路径会<b>整段替换</b>，
     * 工作区根被彻底丢掉。也就是说 {@code resolve(root, "C:\\Windows")} 的结果
     * 就是 {@code C:\Windows} —— 一次拼接就完全跳出了工作区，而且不报错。</p>
     */
    @Test
    @DisplayName("绝对路径：POSIX 根、盘符、盘符相对、UNC 全部拒绝")
    void shouldRejectAbsolutePaths() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("/etc/passwd"));
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("C:\\Windows"));
        // 「盘符相对」路径：C:foo 指的是 C 盘当前目录下的 foo，同样不可控。
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("C:foo"));
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("\\\\server\\share"));
    }

    /**
     * 规则：反斜杠也要当分隔符处理。
     *
     * <p>违反会怎样：模型分不清自己在什么系统上，{@code ..\..\etc} 这种写法一定会出现。
     * 如果只按 {@code /} 分段，这整串会被当成<b>一个文件名</b>，
     * 于是组件检查根本看不到那两个 {@code ..} —— 逃逸就这样躲过了闸门。</p>
     */
    @Test
    @DisplayName("反斜杠分隔符：不能被当成单个文件名绕过组件检查")
    void shouldTreatBackslashAsSeparator() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("..\\..\\etc"));
        // 正常的反斜杠路径要能用，且和正斜杠等价。
        assertEquals(guard.resolveRelative("skills/demo"), guard.resolveRelative("skills\\demo"));
    }

    /**
     * 规则：Windows 保留设备名拒绝，<b>带扩展名的形式也要拒</b>。
     *
     * <p>违反会怎样：往 {@code NUL} 写入会被静默丢弃（数据就这么没了），
     * 读 {@code CON} 会挂在那里等控制台输入。而 {@code CON.txt} 仍然指向设备 ——
     * 这条最容易漏，只做名字全等比较就会放过它。</p>
     *
     * <p>在 Linux 上也要拒：教学工程要在两个平台行为一致，
     * 否则「本机测试通过、换台机器出问题」是最难查的那类 bug。</p>
     */
    @Test
    @DisplayName("Windows 保留设备名：含带扩展名与不同大小写的形式")
    void shouldRejectWindowsReservedNames() {
        assertTrue(WorkspaceGuard.isReservedComponent("CON"));
        assertTrue(WorkspaceGuard.isReservedComponent("nul"));
        assertTrue(WorkspaceGuard.isReservedComponent("COM1"));
        assertTrue(WorkspaceGuard.isReservedComponent("LPT9"));
        // 带扩展名仍然是设备。
        assertTrue(WorkspaceGuard.isReservedComponent("CON.txt"));
        assertTrue(WorkspaceGuard.isReservedComponent("Aux.log"));
        // 正常名字不能被误伤。
        assertFalse(WorkspaceGuard.isReservedComponent("console"));
        assertFalse(WorkspaceGuard.isReservedComponent("com10"));
        assertFalse(WorkspaceGuard.isReservedComponent("readme.md"));
    }

    /**
     * 规则：尾随空格或点号拒绝。
     *
     * <p>违反会怎样：Windows 在打开文件前会<b>静默剥掉</b>尾随的点和空格，
     * 于是 {@code "secret.txt "} 实际打开的是 {@code secret.txt}。
     * 如果上层有基于文件名的白名单，加一个空格就能拿到「不同的名字、同一个文件」。</p>
     */
    @Test
    @DisplayName("尾随空格或点号：拒绝")
    void shouldRejectTrailingSpaceOrDot() {
        assertTrue(WorkspaceGuard.isReservedComponent("note.txt "));
        assertTrue(WorkspaceGuard.isReservedComponent("note.txt."));
        assertFalse(WorkspaceGuard.isReservedComponent("note.txt"));
    }

    /**
     * 规则：控制字符和 Windows 非法字符拒绝。
     *
     * <p>{@code :} 单独说一句：它挡的是 NTFS 备用数据流（ADS）。
     * {@code file.txt:hidden} 会把内容写进一个看起来正常的文件的隐藏流里，
     * 常规的目录列表看不到它。</p>
     */
    @Test
    @DisplayName("控制字符与 Windows 非法字符：拒绝（含 NTFS 备用数据流写法）")
    void shouldRejectControlAndIllegalCharacters() {
        assertTrue(WorkspaceGuard.isReservedComponent("file:stream"));
        assertTrue(WorkspaceGuard.isReservedComponent("bad\u0001name"));
        assertTrue(WorkspaceGuard.isReservedComponent("pipe|name"));
        assertTrue(WorkspaceGuard.isReservedComponent("quote\"name"));
    }

    /** 规则：空串、全空白、NUL 字符拒绝。 */
    @Test
    @DisplayName("空输入与 NUL 字符：拒绝")
    void shouldRejectEmptyAndNul() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative(""));
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("   "));
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("a\u0000b"));
        // "./" 拆完什么都不剩，等于指向工作区根，不是一个子路径。
        assertThrows(WorkspacePathException.class, () -> guard.resolveRelative("./"));
    }

    /**
     * 规则：{@link WorkspaceGuard#isInside} 必须按<b>组件</b>比较，不能按字符串前缀。
     *
     * <p>违反会怎样：字符串前缀会把 {@code /work-evil} 判成在 {@code /work} 之内 ——
     * 前缀确实匹配上了，但那是两个完全不同的目录。攻击者只要在工作区旁边建一个
     * 名字以工作区名开头的目录，就能被判成「在区内」。</p>
     */
    @Test
    @DisplayName("包含性判断：按组件比较，同前缀的兄弟目录不算在内")
    void shouldCompareByComponentNotStringPrefix() {
        Path work = tempDir.resolve("work");
        Path sibling = tempDir.resolve("work-evil");

        assertTrue(WorkspaceGuard.isInside(work, work.resolve("a/b")));
        assertTrue(WorkspaceGuard.isInside(work, work), "自身算在内");
        assertFalse(WorkspaceGuard.isInside(work, sibling),
                "work-evil 只是名字前缀相同，不在 work 之内");
    }

    /**
     * 规则：<b>物理关能挡住词法关挡不住的东西</b> —— 指向区外的符号链接。
     *
     * <p>这是两道关必须都有的证据。{@code escape} 这个字符串在词法上完全合法，
     * 但它是一个指向工作区外的链接。只有解析真实路径才能发现。</p>
     *
     * <p>符号链接在 Windows 上通常需要管理员权限或开发者模式，
     * 建不出来时跳过这条 —— 但<b>不静默跳过</b>，会打印一行说明，
     * 否则「测试全绿」会让人误以为这条边界被验证过了。</p>
     */
    @Test
    @DisplayName("符号链接逃逸：词法合法但物理越界，必须被物理关拦下")
    void shouldRejectSymlinkEscapeAtPhysicalGate() throws IOException {
        Path workspace = Files.createDirectory(tempDir.resolve("ws"));
        Path outside = Files.createDirectory(tempDir.resolve("outside"));
        Path link = workspace.resolve("escape");
        try {
            Files.createSymbolicLink(link, outside);
        } catch (IOException | UnsupportedOperationException e) {
            System.out.println("跳过符号链接测试：本机无法创建符号链接（"
                    + e.getClass().getSimpleName() + "）");
            return;
        }

        WorkspaceGuard guard = WorkspaceGuard.open(workspace.toString());
        // 词法关放行：字符串本身没有任何问题。
        Path lexical = guard.resolveRelative("escape");
        assertTrue(WorkspaceGuard.isInside(guard.getRoot(), lexical),
                "词法上它就在工作区内 —— 这正是词法关不够用的原因");

        // 物理关拦下：解析真实路径后发现它指向区外。
        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.realDirectoryInside(lexical, guard.getRoot()));
    }

    /** 规则：不存在的路径过不了物理关，但过得了词法关 —— 两关的分工。 */
    @Test
    @DisplayName("不存在的路径：词法关放行，物理关拒绝")
    void shouldSeparateLexicalFromPhysicalForMissingPath() {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());

        // 词法关不要求存在：要新建的文件还没有，此时只能靠词法关。
        Path lexical = guard.resolveRelative("not-created-yet.txt");
        assertTrue(WorkspaceGuard.isInside(guard.getRoot(), lexical));

        // 物理关要求存在。
        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.realFileInside(lexical, guard.getRoot()));
    }

    /** 规则：目录当文件用、文件当目录用，都要被物理关分开。 */
    @Test
    @DisplayName("类型检查：目录不能当文件用，反之亦然")
    void shouldRejectWrongFileType() throws IOException {
        WorkspaceGuard guard = WorkspaceGuard.open(tempDir.toString());
        Path directory = Files.createDirectory(tempDir.resolve("adir"));
        Path file = Files.write(tempDir.resolve("afile.txt"), "x".getBytes("UTF-8"));

        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.realFileInside(directory, guard.getRoot()));
        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.realDirectoryInside(file, guard.getRoot()));
    }

    /** 规则：工作区本身不存在或不是目录时，构造期就失败。 */
    @Test
    @DisplayName("工作区非法：构造期直接拒绝")
    void shouldRejectBadWorkspaceAtOpen() throws IOException {
        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.open(tempDir.resolve("nope").toString()));
        assertThrows(WorkspacePathException.class, () -> WorkspaceGuard.open(""));
        assertThrows(WorkspacePathException.class, () -> WorkspaceGuard.open(null));

        Path file = Files.write(tempDir.resolve("f.txt"), "x".getBytes("UTF-8"));
        assertThrows(WorkspacePathException.class,
                () -> WorkspaceGuard.open(file.toString()),
                "工作区必须是目录，不能是文件");
    }
}
