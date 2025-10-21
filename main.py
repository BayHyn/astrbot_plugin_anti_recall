import asyncio
import json
import time
import pickle
from pathlib import Path
from collections import OrderedDict
from .utils import delete_file, delayed_delete, get_private_unified_msg_origin
from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.api.star import StarTools
from astrbot.api import message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult


@register("astrbot_plugin_anti_recall", "JOJO",
          "[仅限aiocqhttp] 防撤回插件，开启监控指定会话后，该会话内撤回的消息将转发给指定接收者", "0.0.2")
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

        self.temp_path = Path(StarTools.get_data_dir()) / "anti_recall_cache"
        self.temp_path.mkdir(exist_ok=True)

        # 内存缓存：key为 (group_id, message_id)，value为 (timestamp, message_chain)
        # 使用OrderedDict实现LRU缓存，最多缓存1000条消息
        self.message_cache = OrderedDict()
        self.max_cache_size = 1000
        self.cache_expire_time = 30 * 60  # 30分钟

        # 清理临时目录中的时间戳大于30分钟的文件
        current_time = time.time() * 1000
        cleaned_count = 0
        for file in self.temp_path.glob("*.pkl"):
            try:
                file_create_time = int(file.name.split('_')[0])
                if current_time - file_create_time > 30 * 60 * 1000:  # 30分钟
                    delete_file(file)
                    cleaned_count += 1
            except (ValueError, IndexError):
                # 如果文件名格式不正确，也删除
                delete_file(file)
                cleaned_count += 1
        logger.info(f'[防撤回插件] 清理临时目录完成，共清理 {cleaned_count} 个过期文件')
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

    def add_to_cache(self, group_id: str, message_id: str, message):
        """添加消息到内存缓存"""
        cache_key = (group_id, message_id)
        current_time = time.time()

        # 如果缓存已满，删除最旧的消息
        if len(self.message_cache) >= self.max_cache_size:
            self.message_cache.popitem(last=False)

        # 添加到缓存
        self.message_cache[cache_key] = (current_time, message)
        self.message_cache.move_to_end(cache_key)

        # 清理过期缓存
        self._clean_expired_cache()

    def get_from_cache(self, group_id: str, message_id: str):
        """从内存缓存获取消息"""
        cache_key = (group_id, message_id)

        if cache_key in self.message_cache:
            timestamp, message = self.message_cache[cache_key]
            current_time = time.time()

            # 检查是否过期
            if current_time - timestamp <= self.cache_expire_time:
                # 移动到末尾（LRU）
                self.message_cache.move_to_end(cache_key)
                return message
            else:
                # 过期了，删除
                del self.message_cache[cache_key]

        return None

    def _clean_expired_cache(self):
        """清理过期的缓存项"""
        current_time = time.time()
        expired_keys = []

        for cache_key, (timestamp, _) in self.message_cache.items():
            if current_time - timestamp > self.cache_expire_time:
                expired_keys.append(cache_key)
            else:
                # 由于OrderedDict是有序的，遇到第一个未过期的就可以停止了
                break

        # 删除过期项
        for key in expired_keys:
            del self.message_cache[key]

    def find_message_file(self, group_id: str, message_id: str):
        """查找消息文件，尝试多种匹配方式"""
        # 方法1：精确匹配最近30分钟的文件
        current_time = time.time() * 1000
        time_range = 30 * 60 * 1000  # 30分钟

        # 按时间倒序查找，优先查找最新的文件
        matching_files = []
        for file in self.temp_path.glob("*.pkl"):
            try:
                parts = file.name.split('_')
                if len(parts) >= 3:
                    file_time = int(parts[0])
                    file_group = parts[1]
                    file_msg_id = parts[2].replace('.pkl', '')

                    # 检查是否在时间范围内且匹配group_id和message_id
                    if (current_time - file_time <= time_range and
                        file_group == group_id and
                        file_msg_id == message_id):
                        matching_files.append((file_time, file))
            except (ValueError, IndexError):
                continue

        # 如果找到多个匹配的文件，返回最新的那个
        if matching_files:
            matching_files.sort(reverse=True)  # 按时间倒序
            return matching_files[0][1]  # 返回最新的文件

        # 方法2：使用通配符匹配（兼容旧版本）
        pattern = f"*_{group_id}_{message_id}.pkl"
        files = list(self.temp_path.glob(pattern))
        if files:
            return files[0]

        return None

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

            # 同时保存到内存缓存和文件
            self.add_to_cache(group_id, message_id, message)

            file_name = '{}_{}_{}.pkl'.format(
                int(time.time() * 1000), group_id, message_id
            )
            file_path = self.temp_path / file_name
            with open(file_path, 'wb') as f:
                pickle.dump(message, f)
            # 延长文件保存时间到30分钟
            asyncio.create_task(delayed_delete(30 * 60, file_path))

        elif message_name == 'notice.group_recall':
            message = None
            user_id = event.get_sender_id()

            # 首先尝试从内存缓存获取
            message = self.get_from_cache(group_id, message_id)
            found_in_cache = message is not None

            # 如果内存缓存中没有，尝试从文件获取
            if message is None:
                file_path = self.find_message_file(group_id, message_id)
                if file_path and file_path.exists():
                    try:
                        with open(file_path, 'rb') as f:
                            message = pickle.load(f)
                        found_in_file = True
                    except Exception as e:
                        logger.error(f'[防撤回插件] 读取消息文件失败: {e}')
                        message = None
                else:
                    found_in_file = False
            else:
                found_in_file = False

            if message:
                source = "内存缓存" if found_in_cache else "文件缓存"
                logger.info(f'[防撤回插件] 用户: {user_id} 在群组 {group_id} 内撤回了消息 (来源: {source}): {message}')
                for forward_to in forward_to_list:
                    try:
                        await self.context.send_message(
                            forward_to,
                            MessageChain(
                                [Comp.Plain(f'用户: {user_id} 在群组 {group_id} 撤回了消息:\n\n')] + message
                            )
                        )
                    except Exception as e:
                        logger.error(f'[防撤回插件] 转发消息失败: {e}')
            else:
                logger.warning(f'[防撤回插件] 找不到撤回消息的记录: group_id={group_id}, message_id={message_id}')
                # 记录详细的调试信息
                logger.debug(f'[防撤回插件] 内存缓存中的键: {list(self.message_cache.keys())}')
                logger.debug(f'[防撤回插件] 缓存目录中的文件: {[f.name for f in self.temp_path.glob("*.pkl")]}')

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
        user_sids = [user.strip() for user in user_list.split(',')]
        # 先获取group_id是否存在message_origin中
        message_forward = self.config.get("message_forward", [])
        for task in message_forward:
            if task.get("message_origin") == group_id:
                # 如果存在，更新forward_to
                task["forward_to"].extend(user_sids)
                task["forward_to"] = list(set(task["forward_to"]))  # 去重
                break
        else:
            # 如果不存在，添加新的任务
            message_forward.append({    
                "message_origin": group_id,
                "forward_to": user_sids
            })

        self.config.save_config()
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
        self.config.save_config()
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
