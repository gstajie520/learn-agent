package learn.agent.command;

import javax.validation.constraints.NotBlank;

/** POST /api/commands 的请求体。 */
public class CreateCommandRequest {
    /** 用户希望 Agent 执行的自然语言指令，不能是 null、空字符串或纯空格。 */
    @NotBlank(message = "instruction 不能为空")
    private String instruction;

    public String getInstruction() {
        return instruction;
    }

    public void setInstruction(String instruction) {
        this.instruction = instruction;
    }
}
