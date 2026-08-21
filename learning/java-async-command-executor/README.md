# Java 线程池基础：JDK 8 常见写法

## 这课到底是干什么的

智能场景里有很多慢操作：调用 Agent、读取大文件、访问远程服务、生成预览。如果把这些工作直接放在 Web 请求线程里，请求线程就会一直等待；如果每次都 `new Thread`，线程数量又无法统一管理。

线程池这一课的目标不是“写几个测试”，而是学会把一次慢任务交给一组可控的工作线程，并且知道如何等待、超时、取消和处理异常。以后 MQ 消费者收到任务后，也会用类似的执行资源管理方式。

本课暂时不解决 Redis 幂等、MQ 跨服务投递，也不解决真正的 HTTP 异步响应。它只解决：**一个 Java 进程内，如何受控地执行后台任务。**

先运行 [AgentTaskDemo.java](src/main/java/learn/agent/async/AgentTaskDemo.java)，观察主线程和线程池线程各自做什么；再看测试验证失败分支。

## 今天只学四个东西

```text
ExecutorService：线程池
Callable：有返回值的任务
Future：未来的任务结果
TimeUnit：时间单位
```

暂时不学习 `CompletableFuture`，也不自己包装任务状态。先把 JDK 原生写法看懂。

## 第一个完整例子

```java
// 1. 创建一个只有 1 个工作线程的线程池。
ExecutorService executorService = Executors.newFixedThreadPool(1);

// 2. 创建一个有返回值的任务。
Callable<String> task = new Callable<String>() {
    @Override
    public String call() {
        return "scene preview";
    }
};

// 3. 把任务交给线程池，得到 Future。
Future<String> future = executorService.submit(task);

// 4. 等待后台任务完成，最多等待 1 秒。
String result = future.get(1, TimeUnit.SECONDS);

// 5. 关闭线程池。
executorService.shutdown();
```

## 一句一句解释

### 1. 创建线程池

```java
ExecutorService executorService = Executors.newFixedThreadPool(1);
```

`1` 表示线程池里只有一个工作线程。同一时间只能执行一个任务。

### 2. 创建任务

```java
Callable<String> task = new Callable<String>() {
    @Override
    public String call() {
        return "scene preview";
    }
};
```

`Callable<String>` 表示这个任务执行完会返回一个字符串。真正在线程池中运行的是 `call()` 方法。

### 3. 提交任务

```java
Future<String> future = executorService.submit(task);
```

`submit()` 把任务交给线程池。返回的 `future` 不是最终字符串，而是这次任务的结果凭证。

### 4. 获取结果

```java
String result = future.get(1, TimeUnit.SECONDS);
```

当前线程最多等待 1 秒：

- 正常完成：返回字符串；
- 超过 1 秒：抛出 `TimeoutException`；
- 任务被取消：抛出 `CancellationException`；
- 任务内部报错：抛出 `ExecutionException`。

### 5. 关闭线程池

```java
executorService.shutdown();
```

线程池中的线程不会自动消失。使用完成后必须关闭，否则 Java 程序可能一直不退出。

## 本项目为什么还保留 AsyncCommandExecutor

它只是把下面两行集中起来：

```java
ExecutorService executorService = Executors.newFixedThreadPool(threadCount);
executorService.submit(task);
```

主类只有两个公开方法：

```java
Future<String> submit(Callable<String> task)
void shutdown()
```

没有其他中间封装。

## 可运行教学入口

教学入口是 `AgentTaskDemo`，它模拟一次“生成智能场景预览”的请求：

```powershell
Set-Location '.\learning\java-async-command-executor'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o compile
java -cp 'target/classes' learn.agent.async.AgentTaskDemo
```

预期能看到类似顺序：

```text
1. 主线程：收到生成场景预览的请求
2. 主线程：任务已经提交，可以先记录日志或返回任务编号
3. 线程池线程：开始调用 Agent
4. 主线程：收到结果 -> 场景预览生成成功
5. 主线程：关闭线程池
```

第 2 行出现在第 3 行前面，说明 `submit()` 把任务交给线程池后就返回了；第 4 行才等待并取得结果。

注意：如果业务代码紧接着调用 `future.get()`，当前线程仍然会等待。线程池解决的是“任务在哪个线程执行”，不是自动让 HTTP 接口永远不等待。

## 文件阅读顺序

```text
1. README.md 的“这课到底是干什么的”
2. `src/main/java/learn/agent/async/AgentTaskDemo.java`
3. `src/main/java/learn/agent/async/AsyncCommandExecutor.java`
4. `src/test/java/learn/agent/async/AsyncCommandExecutorTest.java`
```

测试类只验证四件事。它们是验收材料，不是本课的全部内容：

| 测试 | 业务含义 |
|---|---|
| `shouldGetTaskResult` | 正常获取 Agent 任务结果 |
| `shouldTimeoutWhenTaskIsTooSlow` | 模型响应太慢时停止等待 |
| `shouldCancelTask` | 用户可以取消任务 |
| `shouldReceiveTaskException` | 后台异常不会凭空消失 |

## 运行

```powershell
Set-Location '.\learning\java-async-command-executor'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o test
```

虽然本机 Maven 使用 JDK 17 启动，但本项目的源码和字节码目标设置为 Java 8。

## 先回答这三个问题

1. `Callable.call()` 是谁执行的：主线程还是线程池线程？
2. `Future` 是任务结果本身，还是获取未来结果的凭证？
3. `future.get()` 和 `executor.submit()` 哪一个可能等待？

---

## 第二课：线程池大小与任务排队

### 为什么要学

假设 RabbitMQ 一次送来 100 条 Agent 任务：

- 每个任务都创建一个线程：线程可能太多，内存和 CPU 上下文切换压力增大；
- 只创建两个线程：同一时间只能执行两个任务，其余任务需要排队；
- 队列无限增长：任务不会立即失败，但可能越积越多，最终耗尽内存；
- 队列有上限：系统容量更明确，满了以后必须拒绝、降级或让 MQ 稍后重试。

因此线程池不是只有“线程数量”，而是三个部分：

```text
工作线程：现在可以执行多少任务
任务队列：暂时可以等待多少任务
拒绝策略：线程和队列都满了怎么办
```

### 本课示例配置

```java
ThreadPoolExecutor executor = new ThreadPoolExecutor(
        2,                              // 核心线程数
        2,                              // 最大线程数
        0,
        TimeUnit.SECONDS,
        new ArrayBlockingQueue<Runnable>(2), // 最多排队两个任务
        new ThreadPoolExecutor.AbortPolicy() // 满了就抛异常
);
```

这个配置的总容量可以暂时理解为：

```text
2 个任务正在执行
+ 2 个任务正在排队
= 同一时刻最多接收 4 个未完成任务
```

注意：这是为了学习而简化的固定线程池配置。生产系统还要根据任务耗时、机器资源、下游限流和 MQ 消费速度进行压测。

### 运行示例

```powershell
Set-Location '.\learning\java-async-command-executor'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o compile
java -cp 'target/classes' learn.agent.async.ThreadPoolQueueDemo
```

重点观察：前两个任务开始执行时，后两个任务会进入队列；当前两个任务完成后，线程才会从队列取出后续任务。

### 和 MQ 的关系

```text
MQ：保存并投递跨服务消息
线程池队列：保存当前 Java 进程中等待执行的任务
```

线程池队列不能替代 MQ：Java 服务重启后，内存队列中的任务可能丢失。MQ 中未确认的消息可以重新投递。
