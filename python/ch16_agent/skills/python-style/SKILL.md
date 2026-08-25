---
name: python-style
description: Use when 编写或审查 Python 模块、类型标注和文件路径；Don't use for SQL 或部署。
---
# Python Style

外部输入先按 `unknown` 思路处理，进入业务逻辑前先做运行时校验。

优先使用 `pathlib` 处理文件路径，并给公共类的字段和方法写清楚中文说明。
