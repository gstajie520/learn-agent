package learn.agent.command;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.nio.charset.StandardCharsets;

import static org.hamcrest.Matchers.anyOf;
import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 命令 API 的行为测试。
 *
 * <p>测试重点不是 Spring 注解本身，而是验证“提交立即返回、随后查询状态”的业务闭环。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
public class CommandControllerTest {
    @Autowired
    private MockMvc mockMvc;

    /** 验证提交接口返回 commandId，后台任务最终可以查询到成功结果。 */
    @Test
    public void shouldSubmitAndQueryCommand() throws Exception {
        // Arrange：准备一个模拟用户的智能场景请求。
        String requestJson = "{\"instruction\":\"把机场场景生成预览\"}";

        // Act：提交命令。接口只接受任务，不应该等待 300 毫秒的后台执行。
        MvcResult submitResult = mockMvc.perform(post("/api/commands")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.commandId").isNotEmpty())
                // 后台线程可能已经开始执行，所以提交瞬间允许是 PENDING 或 RUNNING。
                .andExpect(jsonPath("$.status", anyOf(is("PENDING"), is("RUNNING"))))
                .andReturn();

        // 明确使用 UTF-8，避免 Windows 默认字符集导致中文结果乱码。
        String response = submitResult.getResponse().getContentAsString(StandardCharsets.UTF_8);
        String commandId = response.replaceAll(".*\\\"commandId\\\":\\\"([^\\\"]+)\\\".*", "$1");

        // Act：轮询状态，模拟前端根据 commandId 查询任务进度。
        String finalBody = waitForSuccess(commandId);

        // Assert：后台任务最终成功，并返回预览结果。
        org.junit.jupiter.api.Assertions.assertTrue(finalBody.contains("\"status\":\"SUCCEEDED\""));
        org.junit.jupiter.api.Assertions.assertTrue(finalBody.contains("已生成场景预览：把机场场景生成预览"));
    }

    /** 验证查询不存在的 commandId 时返回 404，而不是伪造一个空结果。 */
    @Test
    public void shouldReturn404WhenCommandDoesNotExist() throws Exception {
        // Act + Assert：查询不存在的命令必须返回统一格式的 404 错误。
        mockMvc.perform(get("/api/commands/not-found"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code", is("COMMAND_NOT_FOUND")))
                .andExpect(jsonPath("$.message", is("command not found: not-found")));
    }

    /** 验证空指令在进入 Service 前就被参数校验拒绝。 */
    @Test
    public void shouldRejectBlankInstruction() throws Exception {
        // Arrange：准备一个 instruction 为空的非法请求。
        String requestJson = "{\"instruction\":\"   \"}";

        // Act + Assert：接口返回 400 和统一错误码，不创建后台任务。
        mockMvc.perform(post("/api/commands")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code", is("INVALID_ARGUMENT")))
                .andExpect(jsonPath("$.message", is("instruction 不能为空")));
    }

    private String waitForSuccess(String commandId) throws Exception {
        for (int attempt = 0; attempt < 20; attempt++) {
            MvcResult result = mockMvc.perform(get("/api/commands/" + commandId))
                    .andExpect(status().isOk())
                    .andReturn();
            String body = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
            if (body.contains("\"status\":\"SUCCEEDED\"")) {
                return body;
            }
            Thread.sleep(50);
        }
        throw new AssertionError("命令在规定时间内没有完成");
    }
}
