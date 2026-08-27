package learn.agent.llm.lesson02;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 读取 {@code .env} 文件里的配置。
 *
 * <p><b>这个类存在的原因</b>：Java 的 {@link System#getenv()} 只能读操作系统的
 * 进程环境变量，<b>不会</b>读 {@code .env} 文件。Python 侧能直接用 {@code .env}，
 * 是因为 {@code python-dotenv} 帮它读了文件再塞进 {@code os.environ}。
 * Java 没有这一层，所以要自己补上，否则同一份 {@code .env}
 * 在 Python 能跑、在 Java 读不到。</p>
 *
 * <p><b>文件放在哪</b>：放在多模块工程根目录
 * {@code learning/agent-java-learning/.env}。{@link #load()} 会从当前工作目录
 * <b>逐级向上</b>查找，所以不管是在工程根目录跑 {@code mvn -o test}（工作目录是根目录），
 * 还是 Maven 在子模块里跑测试（工作目录是 {@code 05-llm-client/}），
 * 都能找到同一份文件。后续阶段新增模块也不用各自配一份。</p>
 *
 * <p><b>{@code .env} 绝不允许提交</b>。{@code learning/agent-java-learning/.gitignore}
 * 已经有 {@code .env} 和 {@code **&#47;.env} 两条规则，同时用
 * {@code !**&#47;.env.example} 放行不含真实值的模板。</p>
 *
 * <p><b>优先级</b>：操作系统环境变量<b>覆盖</b> {@code .env} 里的同名值 ——
 * 和 {@code python-dotenv} 的 {@code load_dotenv()} 默认行为一致。
 * 这个顺序在生产环境很关键：容器和 CI 通过真实环境变量注入密钥，
 * 不能被镜像里残留的 {@code .env} 覆盖掉。见
 * {@link ModelSettings#fromEnvironmentOrDotEnv()}。</p>
 *
 * <p><b>本类不做的事</b>（刻意保持简单，够用就行）：不支持
 * {@code ${VAR}} 变量插值、不支持多行值、不会把值写进
 * {@code System} 属性。需要这些能力时应换成成熟库。</p>
 */
public class EnvFile {

    /** 默认文件名。 */
    private static final String DEFAULT_FILE_NAME = ".env";

    /** 向上查找的最大层数，避免在异常路径下一直走到磁盘根。 */
    private static final int MAX_PARENT_LEVELS = 8;

    /** 工具类，不允许实例化。 */
    private EnvFile() {
    }

    /**
     * 从当前工作目录逐级向上查找 {@code .env} 并解析。
     *
     * <p>找不到文件时返回<b>空 Map 而不是抛异常</b>：没有 {@code .env}
     * 是完全正常的情况（比如 CI 里只用真实环境变量）。
     * 是否「配置缺失」由 {@link ModelSettings} 判断，不是本类的职责。</p>
     *
     * @return 解析结果；找不到文件时为空 Map，永不为 {@code null}
     */
    public static Map<String, String> load() {
        File found = findUpwards(DEFAULT_FILE_NAME);
        if (found == null) {
            return Collections.emptyMap();
        }
        return loadFrom(found);
    }

    /**
     * 解析指定文件。
     *
     * <p>读不出来时同样返回空 Map，不抛异常 —— 权限问题、编码问题都不应该
     * 让整个程序起不来，缺配置的报错交给 {@link ModelSettings} 统一给出。</p>
     *
     * @param file 要解析的文件，可以为 {@code null}
     * @return 解析结果，永不为 {@code null}
     */
    public static Map<String, String> loadFrom(File file) {
        Map<String, String> values = new LinkedHashMap<String, String>();
        if (file == null || !file.isFile()) {
            return values;
        }

        BufferedReader reader = null;
        try {
            // 固定用 UTF-8，不跟随平台默认编码。
            // Windows 默认 GBK，同一份文件在不同机器上解析结果会不一样。
            reader = new BufferedReader(
                    new InputStreamReader(new FileInputStream(file), "UTF-8"));
            String line;
            while ((line = reader.readLine()) != null) {
                parseLine(line, values);
            }
        } catch (IOException e) {
            // 刻意不打印异常内容：异常信息里可能带上文件路径，
            // 而调用方真正需要的「缺哪个变量」由 ModelSettings 报出。
            return values;
        } finally {
            closeQuietly(reader);
        }
        return values;
    }

    /**
     * 解析一行，命中时写入 {@code values}。
     *
     * <p>支持的写法：{@code KEY=value}、{@code export KEY=value}、
     * {@code KEY="value"}、{@code KEY='value'}、行首行尾空格。
     * 跳过空行和以 {@code #} 开头的注释行。</p>
     */
    private static void parseLine(String rawLine, Map<String, String> values) {
        String line = rawLine.trim();
        if (line.isEmpty() || line.startsWith("#")) {
            return;
        }
        // 兼容 shell 习惯的 export 前缀。
        if (line.startsWith("export ")) {
            line = line.substring("export ".length()).trim();
        }

        int separator = line.indexOf('=');
        // 没有等号的行不是配置，直接忽略，不要猜。
        if (separator <= 0) {
            return;
        }

        String key = line.substring(0, separator).trim();
        String value = line.substring(separator + 1).trim();
        if (key.isEmpty()) {
            return;
        }
        values.put(key, stripQuotes(value));
    }

    /**
     * 去掉成对的首尾引号。
     *
     * <p>只在首尾<b>都</b>是同一种引号时才剥，避免把
     * {@code KEY=it's} 这种值里本来就有的引号误删。</p>
     */
    private static String stripQuotes(String value) {
        if (value.length() < 2) {
            return value;
        }
        char first = value.charAt(0);
        char last = value.charAt(value.length() - 1);
        if ((first == '"' && last == '"') || (first == '\'' && last == '\'')) {
            return value.substring(1, value.length() - 1);
        }
        return value;
    }

    /**
     * 从当前工作目录逐级向上查找指定文件名。
     *
     * <p>为什么要向上找：Maven 多模块构建时，Surefire 的工作目录是
     * <b>各子模块目录</b>而不是工程根目录。写死相对路径的话，
     * 在根目录跑 {@code mvn test} 能读到，在子模块里跑就读不到，
     * 表现为「同样的配置有时生效有时不生效」，非常难排查。</p>
     *
     * @return 找到的文件；找不到返回 {@code null}
     */
    static File findUpwards(String fileName) {
        String workingDir = System.getProperty("user.dir");
        if (workingDir == null || workingDir.trim().isEmpty()) {
            return null;
        }

        File current = new File(workingDir);
        for (int level = 0; level <= MAX_PARENT_LEVELS && current != null; level++) {
            File candidate = new File(current, fileName);
            if (candidate.isFile()) {
                return candidate;
            }
            current = current.getParentFile();
        }
        return null;
    }

    private static void closeQuietly(BufferedReader reader) {
        if (reader == null) {
            return;
        }
        try {
            reader.close();
        } catch (IOException ignored) {
            // 关闭失败不影响已读到的内容。
        }
    }
}
