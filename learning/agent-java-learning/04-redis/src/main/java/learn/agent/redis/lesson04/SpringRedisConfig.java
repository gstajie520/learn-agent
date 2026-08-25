package learn.agent.redis.lesson04;

import learn.agent.redis.lesson05.SpringRedisStringCacheClient;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Spring Redis 配置。
 *
 * <p>把 Redis 连接交给 Spring 管理，业务类只需要注入 StringRedisTemplate，
 * 不再自己创建和关闭 RedisClient。</p>
 */
@Configuration
public class SpringRedisConfig {

    /** 创建由 Spring 管理的 Redis 连接工厂。 */
    @Bean(destroyMethod = "destroy")
    public LettuceConnectionFactory redisConnectionFactory() {
        RedisStandaloneConfiguration configuration = new RedisStandaloneConfiguration(
                "127.0.0.1", 6379);
        String password = System.getenv("REDIS_PASSWORD");
        if (password != null && !password.trim().isEmpty()) {
            configuration.setPassword(password);
        }
        return new LettuceConnectionFactory(configuration);
    }

    /** 创建字符串版本的 RedisTemplate，避免本课引入对象序列化复杂配置。 */
    @Bean
    public StringRedisTemplate stringRedisTemplate(LettuceConnectionFactory factory) {
        return new StringRedisTemplate(factory);
    }

    /** 创建命令状态存储对象。 */
    @Bean
    public SpringRedisCommandStateStore springRedisCommandStateStore(
            StringRedisTemplate redisTemplate) {
        return new SpringRedisCommandStateStore(redisTemplate);
    }

    /** 创建只负责条件状态更新的业务服务。 */
    @Bean
    public SpringRedisCommandStateService springRedisCommandStateService(
            StringRedisTemplate redisTemplate) {
        return new SpringRedisCommandStateService(redisTemplate);
    }

    /** 创建字符串缓存客户端，供缓存课程的业务服务使用。 */
    @Bean
    public SpringRedisStringCacheClient springRedisStringCacheClient(
            StringRedisTemplate redisTemplate) {
        return new SpringRedisStringCacheClient(redisTemplate);
    }
}
