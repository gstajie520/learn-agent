package learn.agent.command;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 统一处理 Controller 抛出的错误。
 *
 * <p>这样前端不用分别猜测 Spring 默认错误格式，所有业务错误都遵循
 * {@code code + message} 结构。</p>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 处理请求体字段校验失败，例如 instruction 为空。 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiErrorResponse> handleValidation(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult()
                .getFieldErrors()
                .get(0)
                .getDefaultMessage();
        return ResponseEntity.badRequest()
                .body(new ApiErrorResponse("INVALID_ARGUMENT", message));
    }

    /** 处理业务层找不到命令的情况。 */
    @ExceptionHandler(CommandNotFoundException.class)
    public ResponseEntity<ApiErrorResponse> handleCommandNotFound(CommandNotFoundException exception) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(new ApiErrorResponse("COMMAND_NOT_FOUND", exception.getMessage()));
    }

    /** 处理暂未分类的系统异常，避免把堆栈细节直接暴露给前端。 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiErrorResponse> handleUnexpected(Exception exception) {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(new ApiErrorResponse("INTERNAL_ERROR", "服务器内部错误"));
    }
}
