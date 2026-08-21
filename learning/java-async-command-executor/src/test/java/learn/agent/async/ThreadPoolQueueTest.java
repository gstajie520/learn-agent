package learn.agent.async;

import org.junit.jupiter.api.Test;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 线程池队列规则测试。
 *
 * <p>主课程先看 ThreadPoolQueueDemo。这里使用 CountDownLatch 只是为了让
 * 工作线程暂时停住，从而稳定验证队列容量和拒绝策略，不要求现在掌握它。</p>
 */
public class ThreadPoolQueueTest {

    /** 验证工作线程忙碌时，新任务会进入有界队列等待。 */
    @Test
    public void shouldPutTaskIntoQueueWhenWorkerIsBusy() throws Exception {
        // Arrange：一个工作线程、一个等待位置。
        ThreadPoolExecutor executor = createExecutor(1, 1);
        CountDownLatch gate = new CountDownLatch(1);

        try {
            // 第一个任务占用唯一的工作线程。
            executor.submit(createWaitingTask(gate));

            // Act：第二个任务无法立即执行，只能进入队列。
            executor.submit(createWaitingTask(gate));

            // Assert：队列里正好有一个等待任务。
            assertEquals(1, executor.getQueue().size());
        } finally {
            gate.countDown();
            executor.shutdownNow();
        }
    }

    /** 验证线程和队列都满时，继续提交任务会触发拒绝策略。 */
    @Test
    public void shouldRejectTaskWhenWorkerAndQueueAreFull() {
        // Arrange：一个线程正在执行，一个任务已经在队列中等待。
        ThreadPoolExecutor executor = createExecutor(1, 1);
        CountDownLatch gate = new CountDownLatch(1);

        try {
            executor.submit(createWaitingTask(gate));
            executor.submit(createWaitingTask(gate));

            // Act + Assert：第三个任务没有执行位置，也没有排队位置，因此被拒绝。
            assertThrows(
                    RejectedExecutionException.class,
                    () -> executor.submit(createWaitingTask(gate))
            );
        } finally {
            gate.countDown();
            executor.shutdownNow();
        }
    }

    /** 创建固定线程数、固定队列容量的线程池。 */
    private ThreadPoolExecutor createExecutor(int threadCount, int queueSize) {
        return new ThreadPoolExecutor(
                threadCount,
                threadCount,
                0,
                TimeUnit.SECONDS,
                new ArrayBlockingQueue<Runnable>(queueSize),
                new ThreadPoolExecutor.AbortPolicy()
        );
    }

    /** 创建一个等待闸门打开才会结束的测试任务。 */
    private Runnable createWaitingTask(final CountDownLatch gate) {
        return new Runnable() {
            @Override
            public void run() {
                try {
                    gate.await();
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                }
            }
        };
    }
}
