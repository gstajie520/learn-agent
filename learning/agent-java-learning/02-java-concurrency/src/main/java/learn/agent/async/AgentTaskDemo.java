package learn.agent.async;

import java.util.concurrent.Callable;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/**
 * 线程池入门的可运行示例。
 *
 * <p>场景：Java 服务收到“生成智能场景预览”的请求，
 * 把耗时的 Agent 调用交给线程池执行。</p>
 */
public class AgentTaskDemo {

    public static void main(String[] args) {
        AsyncCommandExecutor executor = new AsyncCommandExecutor(1);

        try {
            System.out.println("1. 主线程：收到生成场景预览的请求");

            Future<String> future = executor.submit(new Callable<String>() {
                @Override
                public String call() throws Exception {
                    System.out.println("3. 线程池线程：开始调用 Agent");
                    Thread.sleep(500);
                    return "场景预览生成成功";
                }
            });

            System.out.println("2. 主线程：任务已经提交，可以先记录日志或返回任务编号");

            // 这里调用 get() 后，主线程开始等待任务结果，最多等待 2 秒。
            String result = future.get(2, TimeUnit.SECONDS);
            System.out.println("4. 主线程：收到结果 -> " + result);
        } catch (Exception exception) {
            System.out.println("任务执行失败：" + exception.getMessage());
        } finally {
            executor.shutdown();
            System.out.println("5. 主线程：关闭线程池");
        }
    }
}
