package learn.agent.llm.memory;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 持久化记忆存储：管理 manifest.json、MEMORY.md 和单个记忆文件。
 *
 * <p>文件结构：
 * <ul>
 *   <li>manifest.json：权威文件名列表</li>
 *   <li>MEMORY.md：可重建的索引</li>
 *   <li>*.md：单个记忆文件（frontmatter + body）</li>
 * </ul>
 *
 * <p>线程安全：所有公开方法都是同步的。
 */
public class MemoryStore {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern FRONTMATTER_PATTERN = Pattern.compile(
        "^---\\s*\\n(.*?)\\n---\\s*\\n(.*)$",
        Pattern.DOTALL
    );
    private static final Pattern NAME_PATTERN = Pattern.compile("^name:\\s*(.+)$", Pattern.MULTILINE);
    private static final Pattern DESC_PATTERN = Pattern.compile("^description:\\s*(.+)$", Pattern.MULTILINE);
    private static final Pattern TYPE_PATTERN = Pattern.compile("^\\s+type:\\s*(\\w+)$", Pattern.MULTILINE);

    private final Path root;

    public MemoryStore(Path root) {
        if (root == null) {
            throw new IllegalArgumentException("root must not be null");
        }
        this.root = root;
    }

    /**
     * 读取所有记忆记录。
     */
    public synchronized List<MemoryRecord> records() throws IOException {
        if (!Files.exists(root)) {
            return Collections.emptyList();
        }

        Path manifestPath = root.resolve("manifest.json");
        if (!Files.exists(manifestPath)) {
            return Collections.emptyList();
        }

        List<String> fileNames = readManifest(manifestPath);
        List<MemoryRecord> records = new ArrayList<>();

        for (String fileName : fileNames) {
            Path filePath = root.resolve(fileName);
            if (!Files.exists(filePath)) {
                throw new MemoryStoreException("manifest references missing file: " + fileName);
            }
            records.add(parseMemoryFile(filePath));
        }

        return Collections.unmodifiableList(records);
    }

    /**
     * 渲染记忆目录（name + description）。
     */
    public synchronized String renderCatalog() throws IOException {
        List<MemoryRecord> records = records();
        if (records.isEmpty()) {
            return "";
        }

        StringBuilder sb = new StringBuilder();
        for (MemoryRecord record : records) {
            sb.append("- ").append(record.getName())
              .append(": ").append(record.getDescription())
              .append("\n");
        }
        return sb.toString();
    }

    /**
     * 追加新记忆。
     */
    public synchronized void extend(List<MemoryRecord> newRecords) throws IOException {
        if (newRecords.isEmpty()) {
            return;
        }

        Files.createDirectories(root);

        List<MemoryRecord> existing = records();
        Set<String> existingNames = new HashSet<>();
        for (MemoryRecord record : existing) {
            existingNames.add(record.getName());
        }

        List<String> fileNames = new ArrayList<>();
        if (Files.exists(root.resolve("manifest.json"))) {
            fileNames.addAll(readManifest(root.resolve("manifest.json")));
        }

        for (MemoryRecord record : newRecords) {
            if (existingNames.contains(record.getName())) {
                throw new MemoryStoreException("memory name already exists: " + record.getName());
            }
            String fileName = toFileName(record.getName());
            writeMemoryFile(root.resolve(fileName), record);
            fileNames.add(fileName);
        }

        writeManifest(root.resolve("manifest.json"), fileNames);
        rebuildIndex(existing, newRecords);
    }

    /**
     * 应用整理计划：删除源记忆，写入整理后的记忆。
     */
    public synchronized void applyConsolidation(
        List<MemoryRecord> current,
        List<MemoryRecord> extracted,
        List<String> sourceNames,
        List<MemoryRecord> consolidated
    ) throws IOException {
        // 验证源名称都存在
        Set<String> currentNames = new HashSet<>();
        for (MemoryRecord record : current) {
            currentNames.add(record.getName());
        }
        Set<String> extractedNames = new HashSet<>();
        for (MemoryRecord record : extracted) {
            extractedNames.add(record.getName());
        }

        for (String sourceName : sourceNames) {
            if (!currentNames.contains(sourceName) && !extractedNames.contains(sourceName)) {
                throw new MemoryStoreException("consolidation source not found: " + sourceName);
            }
        }

        Set<String> sourceNameSet = new HashSet<>(sourceNames);

        // 保留未被整理的记忆
        List<MemoryRecord> kept = new ArrayList<>();
        for (MemoryRecord record : current) {
            if (!sourceNameSet.contains(record.getName())) {
                kept.add(record);
            }
        }

        // 添加整理后的记忆
        kept.addAll(consolidated);

        // 重建存储
        List<String> fileNames = new ArrayList<>();
        for (MemoryRecord record : kept) {
            String fileName = toFileName(record.getName());
            writeMemoryFile(root.resolve(fileName), record);
            fileNames.add(fileName);
        }

        writeManifest(root.resolve("manifest.json"), fileNames);
        rebuildIndex(kept, Collections.emptyList());

        // 删除被整理掉的文件
        for (String sourceName : sourceNames) {
            String fileName = toFileName(sourceName);
            if (!fileNames.contains(fileName)) {
                Files.deleteIfExists(root.resolve(fileName));
            }
        }
    }

    private List<String> readManifest(Path manifestPath) throws IOException {
        String content = new String(Files.readAllBytes(manifestPath), StandardCharsets.UTF_8);
        JsonNode root = JSON.readTree(content);
        if (!root.isArray()) {
            throw new MemoryStoreException("manifest must be a JSON array");
        }

        List<String> fileNames = new ArrayList<>();
        for (JsonNode node : root) {
            fileNames.add(node.asText());
        }
        return fileNames;
    }

    private void writeManifest(Path manifestPath, List<String> fileNames) throws IOException {
        ArrayNode array = JSON.createArrayNode();
        for (String fileName : fileNames) {
            array.add(fileName);
        }
        String content = JSON.writerWithDefaultPrettyPrinter().writeValueAsString(array);
        Files.write(manifestPath, content.getBytes(StandardCharsets.UTF_8));
    }

    private MemoryRecord parseMemoryFile(Path filePath) throws IOException {
        String content = new String(Files.readAllBytes(filePath), StandardCharsets.UTF_8);
        Matcher matcher = FRONTMATTER_PATTERN.matcher(content);
        if (!matcher.matches()) {
            throw new MemoryStoreException("memory file has invalid frontmatter: " + filePath);
        }

        String frontmatter = matcher.group(1);
        String body = matcher.group(2).trim();

        Matcher nameMatcher = NAME_PATTERN.matcher(frontmatter);
        if (!nameMatcher.find()) {
            throw new MemoryStoreException("memory file missing name: " + filePath);
        }
        String name = nameMatcher.group(1).trim();

        Matcher descMatcher = DESC_PATTERN.matcher(frontmatter);
        if (!descMatcher.find()) {
            throw new MemoryStoreException("memory file missing description: " + filePath);
        }
        String description = descMatcher.group(1).trim();

        Matcher typeMatcher = TYPE_PATTERN.matcher(frontmatter);
        if (!typeMatcher.find()) {
            throw new MemoryStoreException("memory file missing type: " + filePath);
        }
        String type = typeMatcher.group(1).trim();

        return new MemoryRecord(name, description, MemoryType.fromValue(type), body);
    }

    private void writeMemoryFile(Path filePath, MemoryRecord record) throws IOException {
        StringBuilder sb = new StringBuilder();
        sb.append("---\n");
        sb.append("name: ").append(record.getName()).append("\n");
        sb.append("description: ").append(record.getDescription()).append("\n");
        sb.append("metadata:\n");
        sb.append("  type: ").append(record.getKind().getValue()).append("\n");
        sb.append("---\n\n");
        sb.append(record.getBody()).append("\n");

        Files.write(filePath, sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    private void rebuildIndex(List<MemoryRecord> existing, List<MemoryRecord> newRecords) throws IOException {
        StringBuilder sb = new StringBuilder();
        for (MemoryRecord record : existing) {
            sb.append("- [").append(extractTitle(record.getBody()))
              .append("](").append(toFileName(record.getName()))
              .append(") — ").append(record.getDescription()).append("\n");
        }
        for (MemoryRecord record : newRecords) {
            sb.append("- [").append(extractTitle(record.getBody()))
              .append("](").append(toFileName(record.getName()))
              .append(") — ").append(record.getDescription()).append("\n");
        }

        Files.write(root.resolve("MEMORY.md"), sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    private String extractTitle(String body) {
        String[] lines = body.split("\n", 2);
        if (lines.length > 0 && !lines[0].isEmpty()) {
            return lines[0];
        }
        return "Untitled";
    }

    private String toFileName(String name) {
        return name + ".md";
    }
}
