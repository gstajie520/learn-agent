package learn.agent.llm.structured;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 一次校验的结果：要么通过并带回结果对象，要么失败并带回全部问题。
 *
 * <p><b>为什么不直接抛异常：</b>校验失败是<b>预期内</b>的情况，不是意外。
 * 模型输出不合法太常见了，用异常表达会有两个问题：</p>
 * <ul>
 *   <li>异常一次只能带一个信息，而我们希望一次报出全部问题；</li>
 *   <li>调用方会被迫用 {@code try/catch} 处理正常业务分支，代码很难读。</li>
 * </ul>
 *
 * <p><b>为什么要收集全部错误而不是遇到第一个就返回：</b>这一层的错误信息
 * 是要<b>发回给模型让它重试</b>的。一次告诉它「坐标越界」，它改完再告诉它
 * 「设备类型不支持」，就要多花两轮调用、两倍 token、两倍延迟。
 * 一次性说清所有问题，模型一轮就能改对。</p>
 *
 * <p>这和阶段 3 Spring 的 {@code @Valid} 一次返回全部字段错误、
 * 以及第 2 课 {@link ConfigurationException} 一次报出全部缺失配置，
 * 是同一个道理。</p>
 *
 * @param <T> 校验通过后产出的对象类型
 */
public class ValidationResult<T> {

    /** 校验通过时的产物；失败时为 {@code null}。 */
    private final T value;

    /** 全部错误信息；通过时为空列表。 */
    private final List<String> errors;

    private ValidationResult(T value, List<String> errors) {
        this.value = value;
        this.errors = Collections.unmodifiableList(new ArrayList<String>(errors));
    }

    /** 创建成功结果。 */
    public static <T> ValidationResult<T> ok(T value) {
        if (value == null) {
            throw new IllegalArgumentException("成功结果必须带值");
        }
        return new ValidationResult<T>(value, new ArrayList<String>());
    }

    /** 创建失败结果，带一条错误。 */
    public static <T> ValidationResult<T> fail(String error) {
        List<String> errors = new ArrayList<String>();
        errors.add(error);
        return new ValidationResult<T>(null, errors);
    }

    /** 创建失败结果，带多条错误。 */
    public static <T> ValidationResult<T> fail(List<String> errors) {
        if (errors == null || errors.isEmpty()) {
            throw new IllegalArgumentException("失败结果必须至少有一条错误信息");
        }
        return new ValidationResult<T>(null, errors);
    }

    public boolean isValid() {
        return errors.isEmpty();
    }

    /**
     * 取出校验通过的值。
     *
     * @throws IllegalStateException 校验失败时调用；这是编程错误，
     *         调用方应当先检查 {@link #isValid()}
     */
    public T getValue() {
        if (!isValid()) {
            throw new IllegalStateException("校验未通过，不能取值。错误：" + errors);
        }
        return value;
    }

    /** 返回只读错误列表。 */
    public List<String> getErrors() {
        return errors;
    }

    /**
     * 把全部错误拼成一段可以发回给模型的文本。
     *
     * <p>这段文本会作为下一轮请求的一部分，所以要写得让模型能看懂
     * 「哪里错了、应该怎么改」，而不是内部字段名或 Java 异常信息。</p>
     */
    public String getErrorMessage() {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < errors.size(); i++) {
            if (i > 0) {
                builder.append("；");
            }
            builder.append(errors.get(i));
        }
        return builder.toString();
    }

    @Override
    public String toString() {
        return isValid()
                ? "ValidationResult{ok, value=" + value + "}"
                : "ValidationResult{fail, errors=" + errors + "}";
    }
}
