package learn.agent.command;

import org.springframework.stereotype.Service;

import javax.annotation.PreDestroy;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 命令应用服务。
 *
 * <p>Controller 只负责 HTTP，Service 负责创建命令、提交后台任务和查询状态。</p>
 */
@Service
public class CommandService {
    private final Map<String, CommandRecord> records = new ConcurrentHashMap<String, CommandRecord>();
    private final ExecutorService executorService = Executors.newFixedThreadPool(2);

    /** 创建命令并立即返回，慢任务在后台线程执行。 */
    public CommandRecord submit(String instruction) {
        if (instruction == null || instruction.trim().isEmpty()) {
            throw new IllegalArgumentException("instruction 不能为空");
        }

        String commandId = UUID.randomUUID().toString();
        CommandRecord record = new CommandRecord(commandId, instruction);
        records.put(commandId, record);

        executorService.submit(new Callable<Void>() {
            @Override
            public Void call() {
                execute(record);
                return null;
            }
        });
        return record;
    }

    public CommandRecord find(String commandId) {
        CommandRecord record = records.get(commandId);
        if (record == null) {
            throw new CommandNotFoundException(commandId);
        }
        return record;
    }

    /** Spring Boot 停止时关闭线程池，避免工作线程继续存活。 */
    @PreDestroy
    public void shutdown() {
        executorService.shutdownNow();
    }

    /** 模拟 Agent 慢任务；后续会替换为 MQ 或 Python Agent 调用。 */
    private void execute(CommandRecord record) {
        record.markRunning();
        try {
            Thread.sleep(300);
            record.markSucceeded("已生成场景预览：" + record.getInstruction());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            record.markFailed("任务被中断");
        } catch (Exception exception) {
            record.markFailed("任务执行失败");
        }
    }
}
