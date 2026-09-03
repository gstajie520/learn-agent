package learn.agent.llm.artifact;

/**
 * 消息契约错误：协议要求的字段缺失、类型错误或工具配对违规。
 */
public class MessageContractException extends RuntimeException {
    public MessageContractException(String message) {
        super(message);
    }
}
