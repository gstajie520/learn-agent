# Spring Boot 第二课：请求校验和统一异常

## 这课到底是干什么的

上一课已经把线程池放进了 Spring Boot，但接口还有两个明显问题：空指令也会进入后台任务，查不到命令时错误格式不统一。

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

本课学习请求参数校验和统一异常处理。仍然使用内存 `ConcurrentHashMap`，不连接数据库、Redis、RabbitMQ；存储持久化是后续课程。

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
    public CommandResponse submit(@Valid @RequestBody CreateCommandRequest request) {
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
7. `@Valid`：让 Spring 在调用方法前检查请求对象；校验失败时不会创建线程池任务。

统一异常的返回示例：

```json
{
  "code": "INVALID_ARGUMENT",
  "message": "instruction 不能为空"
}
```

## 完整代码职责

```text
CommandApiApplication.java  Spring Boot 启动入口
CommandController.java      HTTP 路由和状态码
CommandService.java         创建命令、提交线程池、查询状态
CommandRecord.java          内存中的命令状态
CreateCommandRequest.java   请求 DTO
CommandResponse.java        返回 DTO
CommandNotFoundException.java  命令不存在异常
ApiErrorResponse.java       统一错误响应
GlobalExceptionHandler.java 统一异常处理入口
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

第一次查询可能是 `PENDING` 或 `RUNNING`，再次查询会看到 `SUCCEEDED`。

## 这一课暂时不解决什么

- `ConcurrentHashMap` 不是持久化存储，重启会丢数据；
- 没有跨实例幂等，两个服务实例各自有自己的内存；
- 没有 MQ ACK/NACK，线程池任务不是可靠消息；
- 没有权限和数据库事务；本课已经加入基础请求参数校验和统一异常响应。

这些不是遗漏，而是后续课程逐个加入的边界。

## 验收问题

1. 为什么 Controller 不应该直接调用 `Executors.newFixedThreadPool()`？
2. POST 返回 `202 Accepted` 和返回 `200 OK` 的语义有什么不同？
3. 如果 Java 服务重启，当前内存里的命令状态会怎样？
4. 这个项目下一步为什么需要 Redis，而不是继续扩大 `ConcurrentHashMap`？

5. 为什么参数校验应该在进入 Service 前完成？
6. 为什么重复的错误响应格式会增加前端和监控系统的复杂度？
