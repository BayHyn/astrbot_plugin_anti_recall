import os
import traceback
from astrbot.api import logger


def get_private_unified_msg_origin(
    user_id: str, platform: str = "aiocqhttp"
) -> str:
    """获取群组统一消息来源

    Args:
        user_id: 用户ID
        platform: 平台名称

    Returns:
        str: 统一消息来源
    """
    return f"{platform}:FriendMessage:{user_id}"


def delete_file(file_path):
    """删除指定文件，如果文件存在"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"[防撤回插件] 成功删除文件: {file_path}")
        else:
            logger.debug(f"[防撤回插件] 文件不存在: {file_path}")
    except Exception as e:
        logger.error(f"[防撤回插件] 删除文件失败 ({file_path}): {traceback.format_exc()}")
