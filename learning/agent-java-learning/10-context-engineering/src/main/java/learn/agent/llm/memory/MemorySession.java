package learn.agent.llm.memory;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import learn.agent.llm.artifact.ChatMessage;
import learn.agent.llm.artifact.MessageUtils;

import java.util.*;

/**
 * MemorySession 把 MemoryStore 包装成 AgentRunner 可调用的回合生命周期。
 *
 * <p>生命周期：
 * <ul>
 *   <li>回合前：{@link #beginTurn} 选择相关记忆</li>
 *   <li>模型前：{@link #beforeModel} 返回要注入的 system 消息</li>
 *   <li>回合后：{@link #complete} 提取新记忆并整理</li>
 * </ul>
 */
public class MemorySession {
    private static final ObjectMapper JSON = new ObjectMapper();

    private final MemoryStore store;
    private final MemorySelector selector;
    private final MemoryExtractor extractor;
    private final MemoryConsolidator consolidator;
    private final int maxSelected;
    private final int consolidateThreshold;
    private final boolean emitContextMessages;

    // 当前回合选中的只读快照
    private List<MemoryRecord> selected = Collections.emptyList();
    // 记忆 side-query 或持久化失败只记录在此，不阻断主 Agent 回答
    private String lastError;

    public MemorySession(MemoryStore store,
                        MemorySelector selector,
                        MemoryExtractor extractor,
                        MemoryConsolidator consolidator,
                        int maxSelected,
                        int consolidateThreshold,
                        boolean emitContextMessages) {
        if (maxSelected <= 0) {
            throw new IllegalArgumentException("maxSelected must be positive");
        }
        if (consolidateThreshold <= 0) {
            throw new IllegalArgumentException("consolidateThreshold must be positive");
        }

        this.store = store;
        this.selector = selector;
        this.extractor = extractor;
        this.consolidator = consolidator;
        this.maxSelected = maxSelected;
        this.consolidateThreshold = consolidateThreshold;
        this.emitContextMessages = emitContextMessages;
    }

    public List<MemoryRecord> getSelected() {
        return selected;
    }

    public String getLastError() {
        return lastError;
    }

    /**
     * 回合开始先读当前集合；模型选择失败时使用确定性关键词回退。
     */
    public void beginTurn(String query) throws Exception {
        List<MemoryRecord> records = store.records();
        selected = Collections.emptyList();
        lastError = null;

        if (records.isEmpty()) {
            return;
        }

        if (selector != null) {
            try {
                String output = selector.select(query, store.renderCatalog());
                List<String> names = parseSelectedNames(output);
                Map<String, MemoryRecord> byName = new HashMap<>();
                for (MemoryRecord record : records) {
                    byName.put(record.getName(), record);
                }

                // 验证所有名称都存在
                for (String name : names) {
                    if (!byName.containsKey(name)) {
                        throw new MemoryStoreException("selector returned an unknown memory name");
                    }
                }

                // 选择前 maxSelected 个
                List<MemoryRecord> selectedList = new ArrayList<>();
                for (int i = 0; i < Math.min(names.size(), maxSelected); i++) {
                    MemoryRecord record = byName.get(names.get(i));
                    if (record == null) {
                        throw new MemoryStoreException("selector returned an unknown memory name");
                    }
                    selectedList.add(record);
                }
                selected = Collections.unmodifiableList(selectedList);
                return;
            } catch (Exception e) {
                lastError = "Memory selection failed; deterministic fallback used";
            }
        }

        // 回退到关键词选择
        selected = keywordSelect(query, records, maxSelected);
    }

    /**
     * 只把选中记忆作为 system context 附加到下一次模型请求。
     */
    public List<ChatMessage> beforeModel() {
        if (!emitContextMessages || selected.isEmpty()) {
            return Collections.emptyList();
        }
        return Collections.singletonList(ChatMessage.system(renderSelected()));
    }

    /**
     * 渲染选中的记忆为文本。
     */
    public String renderSelected() {
        if (selected.isEmpty()) {
            return "";
        }

        StringBuilder sb = new StringBuilder();
        sb.append("<relevant_memories>\n");
        for (MemoryRecord record : selected) {
            sb.append("\n## ").append(record.getName())
              .append(" (").append(record.getKind().getValue()).append(")\n");
            sb.append(record.getDescription()).append("\n\n");
            sb.append(record.getBody()).append("\n");
        }
        sb.append("\n</relevant_memories>");
        return sb.toString();
    }

    /**
     * 回合结束从完整 canonical history 提取并追加或整理记忆。
     */
    public void complete(List<ChatMessage> history) throws Exception {
        List<MemoryRecord> current = store.records();
        List<MemoryRecord> candidate = current;
        List<MemoryRecord> extracted = Collections.emptyList();

        if (extractor != null) {
            try {
                List<ChatMessage> snapshot = copyHistory(history);
                String output = extractor.extract(snapshot, store.renderCatalog());
                extracted = parseRecordList(output, true);
                candidate = new ArrayList<>(current);
                candidate.addAll(extracted);
                candidate = Collections.unmodifiableList(candidate);
            } catch (Exception e) {
                lastError = "Memory extraction failed";
                return;
            }
        }

        if (consolidator == null || candidate.size() < consolidateThreshold) {
            if (!extracted.isEmpty()) {
                try {
                    store.extend(extracted);
                } catch (Exception e) {
                    lastError = "Memory extraction failed";
                }
            }
            return;
        }

        try {
            String output = consolidator.consolidate(candidate);
            ConsolidationPlan plan = parseConsolidationPlan(output, candidate);
            store.applyConsolidation(current, extracted, plan.sourceNames, plan.records);
        } catch (Exception e) {
            lastError = "Memory consolidation failed";
        }
    }

    private static List<String> parseSelectedNames(String output) {
        try {
            JsonNode root = JSON.readTree(output);
            if (!root.isArray()) {
                throw new MemoryStoreException("selector output must be a JSON string array");
            }

            List<String> names = new ArrayList<>();
            for (JsonNode node : root) {
                names.add(node.asText());
            }

            if (new HashSet<>(names).size() != names.size()) {
                throw new MemoryStoreException("selector output names must be unique");
            }

            return names;
        } catch (Exception e) {
            throw new MemoryStoreException("selector output is not valid JSON", e);
        }
    }

    private static List<MemoryRecord> parseRecordList(String output, boolean allowEmpty) {
        try {
            JsonNode root = JSON.readTree(output);
            if (!root.isArray()) {
                throw new MemoryStoreException("memory model output must be a JSON array");
            }

            List<MemoryRecord> records = new ArrayList<>();
            for (JsonNode node : root) {
                if (!node.has("name") || !node.has("type") || !node.has("description") || !node.has("body")) {
                    throw new MemoryStoreException("memory model item has an invalid schema");
                }

                String name = node.get("name").asText();
                String description = node.get("description").asText();
                String type = node.get("type").asText();
                String body = node.get("body").asText();

                records.add(new MemoryRecord(name, description, MemoryType.fromValue(type), body));
            }

            if (!allowEmpty && records.isEmpty()) {
                throw new MemoryStoreException("memory collection must not be empty");
            }

            return records;
        } catch (Exception e) {
            throw new MemoryStoreException("memory model output is not valid JSON", e);
        }
    }

    private static ConsolidationPlan parseConsolidationPlan(String output, List<MemoryRecord> candidates) {
        try {
            JsonNode root = JSON.readTree(output);
            if (!root.has("source_names") || !root.has("records")) {
                throw new MemoryStoreException("consolidation output has an invalid schema");
            }

            JsonNode sourceNamesNode = root.get("source_names");
            if (!sourceNamesNode.isArray() || sourceNamesNode.size() == 0) {
                throw new MemoryStoreException("consolidation source_names must be a non-empty string array");
            }

            List<String> sourceNames = new ArrayList<>();
            for (JsonNode node : sourceNamesNode) {
                sourceNames.add(node.asText());
            }

            List<MemoryRecord> records = parseRecordList(root.get("records").toString(), false);

            return new ConsolidationPlan(sourceNames, records);
        } catch (Exception e) {
            throw new MemoryStoreException("consolidation output is not valid JSON", e);
        }
    }

    private static List<MemoryRecord> keywordSelect(String query, List<MemoryRecord> records, int limit) {
        Set<String> keywords = keywordTokens(query);

        List<ScoredRecord> ranked = new ArrayList<>();
        for (MemoryRecord record : records) {
            String searchable = (record.getName() + " " + record.getDescription()).toLowerCase();
            int score = 0;
            for (String keyword : keywords) {
                if (searchable.contains(keyword)) {
                    score++;
                }
            }
            if (score > 0) {
                ranked.add(new ScoredRecord(record, score));
            }
        }

        ranked.sort((a, b) -> {
            int scoreDiff = b.score - a.score;
            return scoreDiff != 0 ? scoreDiff : a.record.getName().compareTo(b.record.getName());
        });

        List<MemoryRecord> result = new ArrayList<>();
        for (int i = 0; i < Math.min(ranked.size(), limit); i++) {
            result.add(ranked.get(i).record);
        }

        return Collections.unmodifiableList(result);
    }

    private static Set<String> keywordTokens(String value) {
        Set<String> tokens = new HashSet<>();
        String folded = value.toLowerCase();

        // 英文：至少 3 个字符的 token
        for (String token : folded.split("[^a-z0-9]+")) {
            if (token.length() >= 3) {
                tokens.add(token);
            }
        }

        // 中文：相邻 bigram
        StringBuilder cjkRun = new StringBuilder();
        for (int i = 0; i < folded.length(); i++) {
            char c = folded.charAt(i);
            if (c >= '㐀' && c <= '䶿' || c >= '一' && c <= '鿿') {
                cjkRun.append(c);
            } else {
                if (cjkRun.length() > 0) {
                    processCjkRun(cjkRun.toString(), tokens);
                    cjkRun.setLength(0);
                }
            }
        }
        if (cjkRun.length() > 0) {
            processCjkRun(cjkRun.toString(), tokens);
        }

        return tokens;
    }

    private static void processCjkRun(String run, Set<String> tokens) {
        if (run.length() == 1) {
            tokens.add(run);
            return;
        }
        for (int i = 0; i < run.length() - 1; i++) {
            tokens.add(run.substring(i, i + 2));
        }
    }

    private static List<ChatMessage> copyHistory(List<ChatMessage> history) {
        if (history == null) {
            throw new MemoryStoreException("memory extraction history must not be null");
        }

        List<ChatMessage> copied = new ArrayList<>();
        for (ChatMessage message : history) {
            copied.add(message.deepCopy());
        }

        MessageUtils.validateToolPairing(copied);
        return Collections.unmodifiableList(copied);
    }

    private static class ScoredRecord {
        final MemoryRecord record;
        final int score;

        ScoredRecord(MemoryRecord record, int score) {
            this.record = record;
            this.score = score;
        }
    }

    private static class ConsolidationPlan {
        final List<String> sourceNames;
        final List<MemoryRecord> records;

        ConsolidationPlan(List<String> sourceNames, List<MemoryRecord> records) {
            this.sourceNames = Collections.unmodifiableList(sourceNames);
            this.records = Collections.unmodifiableList(records);
        }
    }
}
