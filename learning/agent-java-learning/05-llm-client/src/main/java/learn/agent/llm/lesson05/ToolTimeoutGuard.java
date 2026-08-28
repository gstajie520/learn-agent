package learn.agent.llm.lesson05;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import learn.agent.llm.lesson04.PreparedToolCall;
import learn.agent.llm.lesson04.ToolContext;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolRegistry;

/**
 * 给工具执行加一个墙上时钟上限：工具卡住时，循环不能跟着一起卡住。
 *
 * <p>第 4 课的 {@link ToolRegistry#invoke} 会兜住工具抛出的异常，但兜不住
 * 「工具永远不返回」。一个连了数据库却忘了设超时的工具，会让整个 Agent
 * 循环无限期挂在那一行，用户看到的是请求没有响应，而不是一条错误。</p>
 *
 * <p>做法是把 invoke 丢到另一个线程，主线程只等固定时长：</p>
 * <pre>{@code
 * Future<ToolExecutionResult> future = executor.submit(() -> registry.invoke(...));
 * future.get(timeoutMillis, MILLISECONDS);   // 超时抛 TimeoutException
 * }</pre>
 *
 * <p><b>必须说清楚一件事：超时只能让「等待」结束，不能让「执行」结束。</b>
 * {@code future.cancel(true)} 发的是线程中断信号，一个不检查中断标志的工具
 * （比如死循环里做纯计算）会继续跑到自然结束。所以超时的含义是
 * 「我不再等它了」，不是「它已经停了」。这也是为什么工具自己也该设超时，
 * 这层只是最后一道防线。</p>
 *
 * <p>用 daemon 线程：工具线程卡住时，JVM 不会因为它还活着而无法退出。</p>
 */
public class ToolTimeoutGuard {

    /** 执行工具的线程池；daemon 线程，避免卡住的工具阻止 JVM 退出。 */
    private final ExecutorService executor;

    /** 单个工具允许的最长执行毫秒数。 */
    private final long timeoutMillis;

    public ToolTimeoutGuard(long timeoutMillis) {
        if (timeoutMillis <= 0) {
            throw new IllegalArgumentException("timeoutMillis 必须为正数");
        }
        this.timeoutMillis = timeoutMillis;
        this.executor = Executors.newCachedThreadPool(new ThreadFactory() {
            @Override
            public Thread newThread(Runnable r) {
                Thread t = new Thread(r, "tool-exec");
                t.setDaemon(true);
                return t;
            }
        });
    }

    public long getTimeoutMillis() {
        return timeoutMillis;
    }

    /**
     * 带超时地执行一次工具调用。
     *
     * <p>三种结果都是<b>返回值</b>，不抛异常，和第 4 课保持一致：
     * 成功、工具自己报的错、超时（{@code tool_timeout}）。</p>
     *
     * @param registry 工具注册表
     * @param prepared 已准备好的调用
     * @param context  受控环境
     * @return 永不为 null
     */
    public ToolExecutionResult invokeWithTimeout(final ToolRegistry registry,
                                                 final PreparedToolCall prepared,
                                                 final ToolContext context) {
        Future<ToolExecutionResult> future = executor.submit(new Callable<ToolExecutionResult>() {
            @Override
            public ToolExecutionResult call() {
                return registry.invoke(prepared, context);
            }
        });
        try {
            return future.get(timeoutMillis, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            // 发中断信号并放弃等待。工具可能还在跑——这一点必须诚实对待。
            future.cancel(true);
            return ToolExecutionResult.error("tool_timeout",
                    "工具执行超过 " + timeoutMillis + "ms，已放弃等待（工具可能仍在后台运行）");
        } catch (InterruptedException e) {
            // 当前线程被中断：恢复中断标志，别把它吞掉。
            Thread.currentThread().interrupt();
            future.cancel(true);
            return ToolExecutionResult.error("tool_interrupted", "等待工具结果时被中断");
        } catch (java.util.concurrent.ExecutionException e) {
            // invoke 内部已经兜住了 RuntimeException，走到这里说明抛的是 Error 之类。
            Throwable cause = e.getCause() == null ? e : e.getCause();
            return ToolExecutionResult.error("tool_execution_error",
                    "工具执行异常：" + cause.getClass().getSimpleName() + ": " + cause.getMessage());
        }
    }

    /** 关闭内部线程池。demo 跑完调用；测试里可以不调，因为是 daemon 线程。 */
    public void shutdown() {
        executor.shutdownNow();
    }
}
