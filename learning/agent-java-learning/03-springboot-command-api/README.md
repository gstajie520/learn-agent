# Spring Boot 第一课：异步命令 HTTP 接口

## 这课到底是干什么的

前面我们已经知道线程池如何执行慢任务，但还没有看到它在真实后端里的位置。

这一课把线程池放进 Spring Boot：

```text
前端 POST /api/commands
        ↓
Controller 接收 HTTP 请求
        ↓
Service 创建 commandId，并提交线程池
        ↓
接口立即返回 PENDING
        ↓
后台任务执行 Agent/远程调用
        ↓
前端 GET /api/commands/{commandId} 查询状态
```

这正是智能场景常见的“提交任务 + 查询状态”模式。它避免 HTTP 请求一直等待 Agent 慢调用。

本课暂时使用内存 `ConcurrentHashMap` 保存状态，不连接数据库、Redis、RabbitMQ。内存只为了看懂 Spring Boot 分层；服务重启后数据会丢失，后面会用 Redis 和数据库解决。

## 先看最小概念示例

```java
@RestController
@RequestMapping("/api/commands")
public class CommandController {
    private final CommandService commandService;

    public CommandController(CommandService commandService) {
        this.commandService = commandService;
    }

    @PostMapping
    public CommandResponse submit(@RequestBody CreateCommandRequest request) {
        return commandService.submit(request.getInstruction());
    }
}
```

逐行理解：

1. `@RestController`：说明这个类处理 HTTP 请求并返回 JSON。
2. `@RequestMapping`：统一接口前缀。
3. 构造方法：Spring 把 `CommandService` 注入进来，Controller 不自己创建 Service。
4. `@PostMapping`：接收 POST 请求。
5. `@RequestBody`：把 JSON 请求体转换成 Java 对象。
6. Controller 只负责接收和返回，真正的业务交给 Service。

## 完整代码职责

```text
CommandApiApplication.java  Spring Boot 启动入口
CommandController.java      HTTP 路由和状态码
CommandService.java         创建命令、提交线程池、查询状态
CommandRecord.java          内存中的命令状态
CreateCommandRequest.java   请求 DTO
CommandResponse.java        返回 DTO
```

## 运行

```powershell
Set-Location '.\learning\agent-java-learning\03-springboot-command-api'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o test
mvn -o spring-boot:run
```

另开一个 PowerShell：

```powershell
$body = '{"instruction":"把机场场景生成预览"}'
$created = Invoke-RestMethod -Method Post -Uri 'http://localhost:8080/api/commands' -ContentType 'application/json' -Body $body
$created
Invoke-RestMethod -Method Get -Uri ("http://localhost:8080/api/commands/" + $created.commandId)
```

第一次查询可能是 `RUNNING`，再次查询会看到 `SUCCEEDED`。

## 这一课暂时不解决什么

- `ConcurrentHashMap` 不是持久化存储，重启会丢数据；
- 没有跨实例幂等，两个服务实例各自有自己的内存；
- 没有 MQ ACK/NACK，线程池任务不是可靠消息；
- 没有权限、参数校验和数据库事务。

这些不是遗漏，而是后续课程逐个加入的边界。

## 验收问题

1. 为什么 Controller 不应该直接调用 `Executors.newFixedThreadPool()`？
2. POST 返回 `202 Accepted` 和返回 `200 OK` 的语义有什么不同？
3. 如果 Java 服务重启，当前内存里的命令状态会怎样？
4. 这个项目下一步为什么需要 Redis，而不是继续扩大 `ConcurrentHashMap`？
