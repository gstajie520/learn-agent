"""第 7 章 Agent：在一次性子 Agent 基础上按需加载 Skill 正文。

这是什么：
    ch07 包的根模块，标识本章的核心特性是按需加载 Skill（技能系统）。

Java 类比：
    类似 Spring Boot 应用的根包，通过包名和模块说明向开发者传达本章核心能力。

为什么需要：
    - 告知开发者本章在 ch06（子 Agent + TODO）基础上新增了 Skill 延迟加载
    - 启动时只扫描 frontmatter（name + description），不读取完整正文
    - 模型调用 load_skill 工具时才加载完整 Skill 内容，节省 System Prompt 空间
"""
