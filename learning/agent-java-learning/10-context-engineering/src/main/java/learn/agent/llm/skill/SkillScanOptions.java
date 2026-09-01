package learn.agent.llm.skill;

/**
 * 扫描时的<b>预算</b>配置。这三个值控制的是「目录会占多少系统提示」，
 * 不控制正文 —— 正文永远是按需读的，不进预算。
 */
public final class SkillScanOptions {

    /** 默认的 Skill 根目录名，相对工作区。 */
    public static final String DEFAULT_DIRECTORY = "skills";

    /** 目录里最多列几条。 */
    public static final int DEFAULT_MAX_ENTRIES = 100;

    /** 目录渲染成文本后的 UTF-8 字节上限。 */
    public static final int DEFAULT_MAX_BYTES = 8000;

    private final String skillsDirectory;
    private final int maxEntries;
    private final int maxBytes;

    /**
     * <p><b>为什么条目数和字节数两个上限都要。</b>只限条目数挡不住「100 个 Skill
     * 每个写了 500 字的描述」；只限字节数会让目录在某个字节位置被切断，
     * 于是模型看到半行。两个一起用，才能保证「要么整条列出，要么不列」。</p>
     *
     * @param skillsDirectory 相对工作区的 Skill 根目录；null 用默认
     * @param maxEntries      条目数上限，必须为正
     * @param maxBytes        字节数上限，必须为正
     */
    public SkillScanOptions(String skillsDirectory, int maxEntries, int maxBytes) {
        if (maxEntries <= 0) {
            throw new IllegalArgumentException("maxEntries 必须为正数，实际 " + maxEntries);
        }
        if (maxBytes <= 0) {
            throw new IllegalArgumentException("maxBytes 必须为正数，实际 " + maxBytes);
        }
        this.skillsDirectory =
                skillsDirectory == null ? DEFAULT_DIRECTORY : skillsDirectory;
        this.maxEntries = maxEntries;
        this.maxBytes = maxBytes;
    }

    /** 全部取默认值。 */
    public static SkillScanOptions defaults() {
        return new SkillScanOptions(DEFAULT_DIRECTORY, DEFAULT_MAX_ENTRIES, DEFAULT_MAX_BYTES);
    }

    public String getSkillsDirectory() {
        return skillsDirectory;
    }

    public int getMaxEntries() {
        return maxEntries;
    }

    public int getMaxBytes() {
        return maxBytes;
    }
}
