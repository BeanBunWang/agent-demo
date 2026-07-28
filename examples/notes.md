# 项目事实

- Agent runtime 基于 Hugging Face smolagents 的 ToolCallingAgent。
- 所有本地能力都通过显式注册的白名单工具执行。
- 任何写入完成后都必须回读文件并验证结果。
