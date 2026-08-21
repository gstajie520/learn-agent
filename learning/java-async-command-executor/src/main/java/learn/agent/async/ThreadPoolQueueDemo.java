package learn.agent.async;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * 演示线程池的三个核心部分：工作线程、任务队列、拒绝策略。
 *
 * <p>场景：Java 服务短时间内收到多个 Agent 任务，但系统最多只允许
 * 两个任务同时执行，避免模型调用或外部 API 被瞬间压垮。</p>
 */
public class ThreadPoolQueueDemo {

    public static void main(String[] args) {
        // 核心线程数 2：同时最多先运行两个任务。
        // 最大线程数 2：不临时增加更多线程。
        // 队列容量 2：工作线程都忙时，最多再等待两个任务。
        ThreadPoolExecutor executor = new ThreadPoolExecutor(
                2,
                2,
                0,
                TimeUnit.SECONDS,
                new ArrayBlockingQueue<Runnable>(2),
                new ThreadPoolExecutor.AbortPolicy()
        );

        try {
            for (int taskNumber = 1; taskNumber <= 4; taskNumber++) {
                final int currentTaskNumber = taskNumber;

                System.out.println("提交任务 " + currentTaskNumber
                        + "，提交前队列长度：" + executor.getQueue().size());

                executor.submit(new Runnable() {
                    @Override
                    public void run() {
                        String threadName = Thread.currentThread().getName();
                        System.out.println("开始执行任务 " + currentTaskNumber
                                + "，执行线程：" + threadName);

                        try {
                            // 模拟调用 Agent 或远程服务需要一定时间。
                            Thread.sleep(1000);
                        } catch (InterruptedException exception) {
                            Thread.currentThread().interrupt();
                        }

                        System.out.println("完成任务 " + currentTaskNumber);
                    }
                });
            }

            System.out.println("四个任务提交完毕，当前队列长度："
                    + executor.getQueue().size());
        } finally {
            executor.shutdown();
        }
    }
}
