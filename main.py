import json
import time
import pickle
import threading
from pathlib import Path
from .utils import delete_file, get_private_unified_msg_origin
from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.api import message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult


TEMP_PATH = Path(__file__).parent / "temp"
TEMP_PATH.mkdir(exist_ok=True)


@register("astrbot_plugin_anti_recall", "JOJO",
          "[仅限aiocqhttp] 防撤回插件，开启监控指定会话后，该会话内撤回的消息将转发给指定接收者", "0.0.1")
class AntiRecall(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        if isinstance(self.config.get("message_forward"), str):
            self.config["message_forward"] = json.loads(
                self.config.get("message_forward", "[]"), strict=False
            )
        logger.info('[防撤回插件] 成功加载配置: {}'.format(self.config))

        # 清理临时目录中的时间戳大于5分钟的文件
        for file in TEMP_PATH.glob("*.pkl"):
            file_create_time = file.name.split('_')[0]
            if time.time() * 1000 - int(file_create_time) > 5 * 60 * 1000:
                delete_file(file)
        logger.info('[防撤回插件] 清理临时目录完成')
        # self.config.save_config()

    def get_origin_list(self):
        """获取配置中的消息转发任务列表"""
        message_forward = self.config.get("message_forward", [])
        origin_list = []
        for task in message_forward:
            if not isinstance(task, dict):
                logger.warning(f"[防撤回插件] 配置中的任务格式错误: {task}")
                continue
            if "message_origin" not in task or "forward_to" not in task:
                logger.warning(f"[防撤回插件] 配置中的任务缺少必要字段: {task}")
                continue
            origin_list.append(task.get("message_origin"))
        return origin_list

    def get_forward_to_list(self, group_id: str):
        """获取指定群组的转发目标列表"""
        message_forward = self.config.get("message_forward", [])
        for task in message_forward:
            if task.get("message_origin") == group_id:
                return task.get("forward_to", [])
        return []

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_all_message(self, event: AstrMessageEvent):
        raw_message = event.message_obj.raw_message
        group_id = event.get_group_id()
        message_id = raw_message.message_id
        message_name = raw_message.name

        origin_list = self.get_origin_list()
        forward_to_list = self.get_forward_to_list(group_id)
        if group_id not in origin_list:
            logger.debug(f"[防撤回插件] 群组 {group_id} 不在监控列表中，跳过处理")
            return

        if message_name == 'message.group.normal':
            message = event.get_messages()
            file_name = '{}_{}_{}.pkl'.format(
                int(time.time() * 1000), group_id, message_id
            )
            file_path = TEMP_PATH / file_name
            with open(file_path, 'wb') as f:
                pickle.dump(message, f)
            threading.Timer(5 * 60, delete_file, args=(file_path,)).start()
        elif message_name == 'notice.group_recall':
            file_name = '*_{}_{}.pkl'.format(
                group_id, message_id
            )
            file_path = TEMP_PATH / file_name
            # 查找匹配的文件
            file_path = next(TEMP_PATH.glob(file_name), None)
            if file_path and file_path.exists():
                with open(file_path, 'rb') as f:
                    message = pickle.load(f)
                user_id = event.get_sender_id()
                logger.info('[防撤回插件] 用户: {} 在群组 {} 内撤回了消息: {}'.format(user_id, group_id, message))
                for forward_to in forward_to_list:
                    await self.context.send_message(
                        get_private_unified_msg_origin(forward_to),
                        MessageChain(
                            [Comp.Plain('用户: {} 在群组 {} 撤回了消息: \n\n'.format(user_id, group_id))] + message
                        )
                    )
            else:
                logger.warning('[防撤回插件] 找不到撤回消息的记录: {}'.format(file_name))

    @filter.command_group("防撤回", alias={'anti_recall'})
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def anti_recall(self):
        pass

    @anti_recall.command("增加", alias={'添加', 'add'})
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def add_anti_recall_task(self, event: AstrMessageEvent, group_id: str, user_list: str):
        """
        添加防撤回任务(为避免风控，建议不要添加过多用户)
        :param event: AstrMessageEvent
        :param group_id: 群组ID
        :param user_list: 用户列表，逗号(,)分隔
        """
        user_ids = [user.strip() for user in user_list.split(',')]
        # 先获取group_id是否存在message_origin中
        message_forward = self.config.get("message_forward", [])
        for task in message_forward:
            if task.get("message_origin") == group_id:
                # 如果存在，更新forward_to
                task["forward_to"].extend(user_ids)
                task["forward_to"] = list(set(task["forward_to"]))  # 去重
                break
        else:
            # 如果不存在，添加新的任务
            message_forward.append({
                "message_origin": group_id,
                "forward_to": user_ids
            })

        self.config["message_forward"] = json.dumps(message_forward, ensure_ascii=False)
        self.config.save_config()
        self.config['message_forward'] = message_forward
        user_ids = self.get_forward_to_list(group_id)
        yield event.plain_result(
            f"[防撤回插件] 成功添加防撤回任务到群组 {group_id}，剩余接收用户: {','.join(user_ids)}"
        )

    @anti_recall.command("删除", alias={'移除', 'remove', 'rm', 'delete', 'del'})
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def remove_anti_recall_task(self, event: AstrMessageEvent, group_id: str, user_list: str):
        """
        删除防撤回任务
        :param event: AstrMessageEvent
        :param group_id: 群组ID
        :param user_list: 用户列表，逗号(,)分隔
        """
        user_ids = [user.strip() for user in user_list.split(',')]
        message_forward = self.config.get("message_forward", [])
        for task in message_forward:
            if task.get("message_origin") == group_id:
                # 如果存在，删除forward_to中的用户
                task["forward_to"] = [user for user in task["forward_to"] if user not in user_ids]
                if not task["forward_to"]:
                    message_forward.remove(task)
                break
        else:
            logger.warning(f"[防撤回插件] 未找到群组 {group_id} 的防撤回任务")
        self.config["message_forward"] = json.dumps(message_forward, ensure_ascii=False)
        self.config.save_config()
        self.config['message_forward'] = message_forward
        forward_to_list = self.get_forward_to_list(group_id)
        if not forward_to_list:
            # 如果没有接收用户了，删除整个任务
            yield event.plain_result(
                f"[防撤回插件] 成功从群组 {group_id} 删除防撤回任务，接收用户已全部移除"
            )
        else:
            yield event.plain_result(
                f"[防撤回插件] 成功从群组 {group_id} 删除防撤回任务，接收用户: {', '.join(forward_to_list)}"
            )

    @anti_recall.command("查看", alias={'list', 'show', 'ls'})
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def list_anti_recall_tasks(self, event: AstrMessageEvent):
        """
        查看当前防撤回任务列表
        :param event: AstrMessageEvent
        """
        message_forward = self.config.get("message_forward", [])
        if not message_forward:
            yield event.plain_result("[防撤回插件] 当前没有任何防撤回任务")
            return

        result = "[防撤回插件] 当前防撤回任务列表:\n"
        for task in message_forward:
            group_id = task.get("message_origin")
            forward_to = task.get("forward_to", [])
            result += f"群组ID: {group_id}, 接收用户: {','.join(forward_to)}\n"
        yield event.plain_result(result)
