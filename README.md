<div align="center">

![插件标识](https://count.getloli.com/@astrbot_plugin_anti_recall?name=astrbot_plugin_anti_recall&theme=capoo-2&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot\_plugin\_anti\_recall

**[仅限 aiocqhttp] 防撤回插件**

</div>

## 简介

`astrbot_plugin_anti_recall` 是一个专为 `aiocqhttp` 平台设计的防撤回插件。通过开启监控指定会话，该插件可以将会话内被撤回的消息转发给指定的接收者。

## 功能

- **消息监控**：实时监控指定群组的消息撤回事件。
- **消息转发**：将撤回的消息转发给指定的用户。
- **任务管理**：支持添加、删除和查看防撤回任务。
- **自动清理**：定期清理临时文件，确保插件运行高效。

## 已知问题

1. 目前仅支持群聊防撤回，不支持私聊。
2. 因Astrbot框架本身的限制，收到的转发消息可能会存在换行缺失的问题，期待后续Astrbot修复。

| 期望输出                       | 实际输出                           |
|----------------------------|--------------------------------|
| ![img.png](images/img.png) | ![img_1.png](images/img_1.png) |
