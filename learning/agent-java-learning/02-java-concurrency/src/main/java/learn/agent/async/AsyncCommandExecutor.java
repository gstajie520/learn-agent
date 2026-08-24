package learn.agent.async;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/**
 * 使用 JDK 8 线程池执行 Agent 后台任务。
 *
 * <p>这个类只保留两个动作：提交任务、关闭线程池。</p>
 */
public class AsyncCommandExecutor {

    /** 真正管理工作线程的 JDK 线程池。 */
    private final ExecutorService executorService;

    /**
     * 创建固定大小的线程池。
     *
     * @param threadCount 线程数量
     */
    public AsyncCommandExecutor(int threadCount) {
        if (threadCount <= 0) {
            throw new IllegalArgumentException("threadCount must be greater than 0");
        }
        this.executorService = Executors.newFixedThreadPool(threadCount);
    }

    /**
     * 把任务交给线程池执行。
     *
     * @param task 需要在后台执行的任务
     * @return Future，调用方可以用它等待结果或取消任务
     */
    public Future<String> submit(Callable<String> task) {
        if (task == null) {
            throw new IllegalArgumentException("task must not be null");
        }
        return executorService.submit(task);
    }

    /** 关闭线程池，不再接收新任务。 */
    public void shutdown() {
        executorService.shutdownNow();
    }
}
