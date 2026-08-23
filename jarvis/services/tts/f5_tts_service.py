# jarvis/services/tts/f5_tts_service.py
"""F5-TTS 适配层 — 复用 voice-clone-demo 的 TTSService 单例。

通过 sys.path.insert 把 ../voice-clone-demo/web/backend 加进 path，
让 demo 的 TTSService 可直接 import。Jarvis 侧不重复实现 1.2GB 模型的懒加载逻辑。

降级策略:
    available=True 条件链:
        1. settings.voice_clone.enabled == True
        2. ref_audio 与 ref_text 文件都存在
        3. f5_tts 包可导入（未装则 raise F5TTSUnavailable）
        4. TTSService 加载成功（首次会有 1.2GB 下载）
    任一失败 → available=False，调用方走降级协议。
"""
import asyncio
import importlib
import sys
import threading
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)


class F5TTSUnavailable(Exception):
    """F5-TTS 不可用：未装包 / ref 缺失 / 模型加载失败。"""


class F5TTSBridge:
    """F5-TTS 适配 + 懒加载 + 降级判断"""

    def __init__(self):
        self._service = None  # voice-clone-demo 的 TTSService 实例
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._demo_path_added = False
        self._add_demo_to_path()
        self._patch_seed_everything()

    @staticmethod
    def _patch_seed_everything():
        """Monkey-patch f5_tts.model.utils.seed_everything。

        原实现: ``os.environ["PYTHONHASHSEED"] = str(seed)``，其中 seed
        来自 ``random.randint(0, sys.maxsize)``。64 位 macOS 上 sys.maxsize
        远超 Python 允许的 [0, 2**32-1] 范围，子进程启动时直接 Fatal:
        ``config_init_hash_seed: PYTHONHASHSEED must be "random" or an
        integer in range [0; 4294967295]``。

        解决: 把 seed clamp 到 [0, 2**32-1] 后再写环境变量。
        """
        try:
            import f5_tts.model.utils as _f5utils
        except Exception:
            return  # f5-tts 未装就不动

        _orig = _f5utils.seed_everything

        def _clamped(seed=0):
            import random as _rnd
            if seed is None:
                seed = _rnd.randint(0, 2**32 - 1)
            else:
                try:
                    seed = int(seed) & 0xFFFFFFFF
                except (TypeError, ValueError):
                    seed = 0
            _orig(seed)

        _f5utils.seed_everything = _clamped
        # 同时 patch api.py 的本地引用 (它做的是 ``from ... import seed_everything``)
        try:
            import f5_tts.api as _f5api
            _f5api.seed_everything = _clamped
        except Exception:
            pass
        logger.debug("[F5TTS] seed_everything patched (PYTHONHASHSEED clamp)")

    @staticmethod
    def _add_demo_to_path():
        """把 ../voice-clone-demo/web/backend 加进 sys.path，使 TTSService 可被 import"""
        demo_root = (
            Path(settings.storage.base_dir).parent
            / "voice-clone-demo"
            / "web"
            / "backend"
        )
        if demo_root.exists() and str(demo_root) not in sys.path:
            sys.path.insert(0, str(demo_root))
            logger.info(f"[F5TTS] added demo path: {demo_root}")

    def ensure_service(self):
        """懒加载 demo 的 TTSService。缺包/加载失败抛 F5TTSUnavailable。"""
        if self._service is not None:
            return self._service
        with self._lock:
            if self._service is not None:
                return self._service
            try:
                tts_module = importlib.import_module("tts_service")
                self._service = tts_module.service
                logger.info("[F5TTS] TTSService loaded")
            except ImportError as e:
                msg = f"f5-tts 包缺失或 demo backend 不可访问: {e}"
                self._last_error = msg
                logger.warning(f"[F5TTS] {msg}")
                raise F5TTSUnavailable(msg) from e
            except Exception as e:
                msg = f"TTSService 初始化失败: {type(e).__name__}: {e}"
                self._last_error = msg
                logger.warning(f"[F5TTS] {msg}")
                raise F5TTSUnavailable(msg) from e
        return self._service

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def available(self) -> bool:
        """综合判断：enabled + ref 完整 + 服务可加载。"""
        if not settings.voice_clone.enabled:
            return False
        if not (
            settings.voice_clone.ref_audio.exists()
            and settings.voice_clone.ref_text_path.exists()
        ):
            return False
        try:
            self.ensure_service()
            return True
        except F5TTSUnavailable:
            return False

    @property
    def device(self) -> str:
        """推理设备（mps/cuda/cpu/unknown）。"""
        try:
            return self.ensure_service().get_device()
        except Exception:
            return "unknown"

    def get_ref_text(self) -> str:
        p = settings.voice_clone.ref_text_path
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8").strip()

    # ============ 同步合成 ============

    def synthesize_to_wav(
        self,
        text: str,
        output_name: Optional[str] = None,
        speed: Optional[float] = None,
    ) -> dict:
        """整段文本 → wav 文件。

        Returns: { output_url, output_path, duration, sample_rate }
        Raises: F5TTSUnavailable
        """
        service = self.ensure_service()
        speed = speed or settings.voice_clone.speed
        result = service.clone(
            ref_audio=str(settings.voice_clone.ref_audio),
            ref_text=self.get_ref_text(),
            gen_text=text,
            output_name=output_name,
            speed=speed,
        )
        # 改造 output_url: 走 jarvis 静态路由而不是 demo 的 /api/outputs/...
        filename = Path(result["output_path"]).name
        result["output_url"] = f"/api/voice/audio/{filename}"
        return result

    # ============ 流式合成 ============

    async def synthesize_to_pcm(
        self,
        text: str,
        speed: Optional[float] = None,
    ) -> AsyncIterator[bytes]:
        """异步流式合成: yield PCM int16 LE bytes。

        实现: 把 demo 的 _synthesize_iter 包成 async generator。
        F5-TTS 没有真正的 streaming API，我们把整段合成完再分块 yield。
        """
        service = self.ensure_service()
        speed = speed or settings.voice_clone.speed
        async for pcm in service.synthesize_to_pcm(
            ref_audio=str(settings.voice_clone.ref_audio),
            ref_text=self.get_ref_text(),
            gen_text=text,
            speed=speed,
        ):
            yield pcm


# 全局单例
f5_tts = F5TTSBridge()