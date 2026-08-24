package learn.agent.command;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;

/** 智能场景命令 HTTP 接口。 */
@RestController
@RequestMapping("/api/commands")
public class CommandController {
    private final CommandService commandService;

    public CommandController(CommandService commandService) {
        this.commandService = commandService;
    }

    /** 提交命令，只返回命令编号，不等待慢任务完成。 */
    @PostMapping
    public ResponseEntity<CommandResponse> submit(@Valid @RequestBody CreateCommandRequest request) {
        CommandRecord record = commandService.submit(request.getInstruction());
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(CommandResponse.from(record));
    }

    /** 根据 commandId 查询后台任务当前状态。 */
    @GetMapping("/{commandId}")
    public ResponseEntity<CommandResponse> find(@PathVariable String commandId) {
        // Service 找不到命令时抛出 CommandNotFoundException，由统一异常处理器返回 404 JSON。
        CommandRecord record = commandService.find(commandId);
        return ResponseEntity.ok(CommandResponse.from(record));
    }
}
