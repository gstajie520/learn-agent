package learn.agent.llm.client;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 模型配置缺失或格式错误时抛出。
 *
 * <p>为什么单独定义一个异常，而不是直接抛 {@code IllegalArgumentException}：
 * 配置错误和运行时业务错误的处理方式完全不同。配置错误必须在<b>启动阶段</b>
 * 就暴露出来，由人工修改环境变量解决；它不该被重试，也不该在处理用户请求的
 * 半路才被发现。</p>
 *
 * <p>Java 对照：类似 Spring 启动时的配置绑定失败 —— 应用直接起不来，
 * 而不是先启动成功、等第一个请求进来才报错。</p>
 */
public class ConfigurationException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    /** 缺失或非法的配置项名称，供运维一次性修完。 */
    private final List<String> invalidFields;

    public ConfigurationException(List<String> invalidFields) {
        super("缺少或填写错误的必要配置：" + join(invalidFields));
        // 复制并包装成只读：异常创建后不允许外部再修改这个列表。
        this.invalidFields = Collections.unmodifiableList(new ArrayList<String>(invalidFields));
    }

    public List<String> getInvalidFields() {
        return invalidFields;
    }

    private static String join(List<String> fields) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < fields.size(); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(fields.get(i));
        }
        return sb.toString();
    }
}
