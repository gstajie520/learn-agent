package learn.agent.command;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spring Boot 应用入口。
 *
 * <p>启动后，Java 服务会提供提交智能场景命令和查询命令状态的 HTTP 接口。</p>
 */
@SpringBootApplication
public class CommandApiApplication {

    public static void main(String[] args) {
        System.out.println("启动智能场景命令 API：POST /api/commands");
        SpringApplication.run(CommandApiApplication.class, args);
    }
}
