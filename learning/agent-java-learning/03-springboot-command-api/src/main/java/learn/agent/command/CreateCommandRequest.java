package learn.agent.command;

/** POST /api/commands 的请求体。 */
public class CreateCommandRequest {
    private String instruction;

    public String getInstruction() {
        return instruction;
    }

    public void setInstruction(String instruction) {
        this.instruction = instruction;
    }
}
