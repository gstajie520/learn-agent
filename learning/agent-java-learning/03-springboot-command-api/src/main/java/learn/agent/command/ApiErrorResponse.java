package learn.agent.command;

/** 所有接口错误统一返回的 JSON 结构。 */
public class ApiErrorResponse {
    private final String code;
    private final String message;

    public ApiErrorResponse(String code, String message) {
        this.code = code;
        this.message = message;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
