package learn.agent.async;

import org.junit.jupiter.api.Test;

import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * JDK 8 线程池基础测试。
 *
 * <p>本章只使用 JDK 原生的 ExecutorService、Callable 和 Future，
 * 不增加业务状态封装，先把线程池最基本的执行过程看懂。</p>
 */
public class AsyncCommandExecutorTest {

    /** 验证提交 Agent 任务后，可以通过 Future 获取返回结果。 */
    @Test
    public void shouldGetTaskResult() throws Exception {
        // Arrange：创建只有一个工作线程的执行器。
        AsyncCommandExecutor executor = new AsyncCommandExecutor(1);

        try {
            // Act：提交任务。Callable 的 call() 方法就是后台线程要执行的代码。
            Future<String> future = executor.submit(new Callable<String>() {
                @Override
                public String call() {
                    return "scene preview";
                }
            });

            // Future.get() 会等待任务完成，最多等待 1 秒。
            String result = future.get(1, TimeUnit.SECONDS);

            // Assert：验证后台任务返回了预期结果。
            assertEquals("scene preview", result);
        } finally {
            // 无论测试成功还是失败，最后都关闭线程池。
            executor.shutdown();
        }
    }

    /** 验证后台任务执行较慢时，Future.get() 可以触发超时。 */
    @Test
    public void shouldTimeoutWhenTaskIsTooSlow() {
        // Arrange：创建线程池并提交一个需要执行 1 秒的慢任务。
        AsyncCommandExecutor executor = new AsyncCommandExecutor(1);
        Future<String> future = executor.submit(new Callable<String>() {
            @Override
            public String call() throws Exception {
                Thread.sleep(100000);
                return "late result";
            }
        });

        try {
            // Act + Assert：只等 50 毫秒，所以应该抛出 TimeoutException。
            assertThrows(
                    TimeoutException.class,
                    () -> future.get(500, TimeUnit.MILLISECONDS)
            );

            // 超时只代表调用方不再等待；还需要主动取消后台任务。
            future.cancel(true);
            assertTrue(future.isCancelled());
        } finally {
            executor.shutdown();
        }
    }

    /** 验证用户取消任务后，再获取结果会收到 CancellationException。 */
    @Test
    public void shouldCancelTask() {
        // Arrange：提交一个执行时间较长的任务。
        AsyncCommandExecutor executor = new AsyncCommandExecutor(1);
        Future<String> future = executor.submit(new Callable<String>() {
            @Override
            public String call() throws Exception {
                Thread.sleep(1000);
                return "unused result";
            }
        });

        try {
            // Act：true 表示任务正在运行时，允许中断工作线程。
            boolean cancelled = future.cancel(true);

            // Assert：取消成功，并且不能再获取正常结果。
            assertTrue(cancelled);
            assertTrue(future.isCancelled());
            assertThrows(CancellationException.class, future::get);
        } finally {
            executor.shutdown();
        }
    }

    /** 验证后台任务抛出的异常会被 Future 包装成 ExecutionException。 */
    @Test
    public void shouldReceiveTaskException() {
        // Arrange：提交一个模拟模型服务故障的任务。
        AsyncCommandExecutor executor = new AsyncCommandExecutor(1);
        Future<String> future = executor.submit(new Callable<String>() {
            @Override
            public String call() {
                throw new IllegalStateException("model unavailable");
            }
        });

        try {
            // Act：获取后台任务结果时，会收到 ExecutionException。
            ExecutionException exception = assertThrows(
                    ExecutionException.class,
                    future::get
            );

            // Assert：真正的业务异常保存在 getCause() 中。
            assertEquals("model unavailable", exception.getCause().getMessage());
        } finally {
            executor.shutdown();
        }
    }
}
