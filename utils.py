import asyncio
import traceback
from pathlib import Path
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


def delete_file(file_path: Path):
    """删除指定文件，如果文件存在"""
    try:
        # unlink(missing_ok=True) 在 Python 3.8+ 可用，可以避免预先检查
        file_path.unlink(missing_ok=True)
        logger.debug(f"[防撤回插件] 尝试删除文件: {file_path}")
    except Exception as e:
        logger.error(f"[防撤回插件] 删除文件失败 ({file_path}): {traceback.format_exc()}")


async def delayed_delete(delay, path):
    await asyncio.sleep(delay)
    delete_file(path)
