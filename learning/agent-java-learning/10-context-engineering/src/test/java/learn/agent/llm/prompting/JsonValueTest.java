package learn.agent.llm.prompting;

import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * JsonValue 类型系统测试。
 */
class JsonValueTest {

    @Test
    void shouldCreateJsonNull() {
        JsonNull value = JsonValue.ofNull();
        assertThat(value).isSameAs(JsonNull.INSTANCE);
        assertThat(value.toStableJson()).isEqualTo("null");
    }

    @Test
    void shouldCreateJsonBoolean() {
        JsonBoolean trueValue = JsonValue.of(true);
        JsonBoolean falseValue = JsonValue.of(false);

        assertThat(trueValue).isSameAs(JsonBoolean.TRUE);
        assertThat(falseValue).isSameAs(JsonBoolean.FALSE);
        assertThat(trueValue.toStableJson()).isEqualTo("true");
        assertThat(falseValue.toStableJson()).isEqualTo("false");
    }

    @Test
    void shouldCreateJsonNumber() {
        JsonNumber integer = JsonValue.of(42.0);
        JsonNumber decimal = JsonValue.of(3.14);

        assertThat(integer.toStableJson()).isEqualTo("42");
        assertThat(decimal.toStableJson()).isEqualTo("3.14");
    }

    @Test
    void shouldRejectNonFiniteNumbers() {
        assertThatThrownBy(() -> JsonValue.of(Double.NaN))
                .isInstanceOf(PromptContextException.class)
                .hasMessageContaining("non-finite");

        assertThatThrownBy(() -> JsonValue.of(Double.POSITIVE_INFINITY))
                .isInstanceOf(PromptContextException.class)
                .hasMessageContaining("non-finite");

        assertThatThrownBy(() -> JsonValue.of(Double.NEGATIVE_INFINITY))
                .isInstanceOf(PromptContextException.class)
                .hasMessageContaining("non-finite");
    }

    @Test
    void shouldCreateJsonString() {
        JsonString value = JsonValue.of("hello");
        assertThat(value.value()).isEqualTo("hello");
        assertThat(value.toStableJson()).isEqualTo("\"hello\"");
    }

    @Test
    void shouldEscapeJsonString() {
        JsonString value = JsonValue.of("line1\nline2\ttab\"quote\\backslash");
        assertThat(value.toStableJson())
                .isEqualTo("\"line1\\nline2\\ttab\\\"quote\\\\backslash\"");
    }

    @Test
    void shouldRejectNullString() {
        assertThatThrownBy(() -> JsonValue.of((String) null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("cannot be null");
    }

    @Test
    void shouldCreateJsonArray() {
        JsonArray array = JsonValue.of(Arrays.asList(
                JsonValue.of(1.0),
                JsonValue.of("text"),
                JsonValue.ofNull()
        ));

        assertThat(array.size()).isEqualTo(3);
        assertThat(array.toStableJson()).isEqualTo("[1,\"text\",null]");
    }

    @Test
    void shouldCreateJsonObject() {
        Map<String, JsonValue> map = new HashMap<String, JsonValue>();
        map.put("name", JsonValue.of("Alice"));
        map.put("age", JsonValue.of(30.0));
        JsonObject obj = JsonValue.of(map);

        assertThat(obj.size()).isEqualTo(2);
        assertThat(obj.get("name")).isEqualTo(JsonValue.of("Alice"));
        // 键按字母顺序排序
        assertThat(obj.toStableJson()).isEqualTo("{\"age\":30,\"name\":\"Alice\"}");
    }

    @Test
    void shouldSortObjectKeysForStability() {
        Map<String, JsonValue> map1 = new HashMap<String, JsonValue>();
        map1.put("z", JsonValue.of(1.0));
        map1.put("a", JsonValue.of(2.0));
        map1.put("m", JsonValue.of(3.0));
        JsonObject obj1 = JsonValue.of(map1);

        Map<String, JsonValue> map2 = new HashMap<String, JsonValue>();
        map2.put("m", JsonValue.of(3.0));
        map2.put("z", JsonValue.of(1.0));
        map2.put("a", JsonValue.of(2.0));
        JsonObject obj2 = JsonValue.of(map2);

        // 相同内容的对象应该生成相同的稳定 JSON
        assertThat(obj1.toStableJson()).isEqualTo(obj2.toStableJson());
        assertThat(obj1.toStableJson()).isEqualTo("{\"a\":2,\"m\":3,\"z\":1}");
    }

    @Test
    void shouldHandleNestedStructures() {
        Map<String, JsonValue> tagsMap = new HashMap<String, JsonValue>();
        tagsMap.put("name", JsonValue.of("Bob"));
        tagsMap.put("tags", JsonValue.of(Arrays.asList(
                JsonValue.of("admin"),
                JsonValue.of("developer")
        )));

        Map<String, JsonValue> userMap = new HashMap<String, JsonValue>();
        userMap.put("user", JsonValue.of(tagsMap));
        JsonObject nested = JsonValue.of(userMap);

        assertThat(nested.toStableJson())
                .isEqualTo("{\"user\":{\"name\":\"Bob\",\"tags\":[\"admin\",\"developer\"]}}");
    }

    @Test
    void shouldImplementEqualsAndHashCode() {
        Map<String, JsonValue> map1 = new HashMap<String, JsonValue>();
        map1.put("x", JsonValue.of(1.0));
        JsonObject obj1 = JsonValue.of(map1);

        Map<String, JsonValue> map2 = new HashMap<String, JsonValue>();
        map2.put("x", JsonValue.of(1.0));
        JsonObject obj2 = JsonValue.of(map2);

        assertThat(obj1).isEqualTo(obj2);
        assertThat(obj1.hashCode()).isEqualTo(obj2.hashCode());
    }
}
