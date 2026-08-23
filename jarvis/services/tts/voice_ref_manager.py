# jarvis/services/tts/voice_ref_manager.py
"""参考音频（克隆声音的音色样本）持久化管理。

存储:
    workspace/voice/refs/
        voice.wav             ← active 参考音频
        voice.txt             ← active 参考文本（必填，F5-TTS 用）
        history/              ← 旧版本归档
            voice_<ts>.wav
            voice_<ts>.txt

非 wav 格式（mp3/m4a/ogg/flac/webm）用 ffmpeg 转 24kHz mono s16 wav。
"""
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from jarvis.config import settings
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

ALLOWED_EXT = {"wav", "mp3", "m4a", "ogg", "flac", "webm"}


class VoiceRefManager:
    """参考音频 CRUD"""

    def __init__(self):
        self.refs_dir: Path = settings.voice_clone.refs_dir
        self.history_dir: Path = self.refs_dir / "history"
        self.refs_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        # 首次启动: 如果 ref_text 文件不存在, 写入默认文本
        if not self.active_text_path.exists():
            self.active_text_path.write_text(
                settings.voice_clone.default_ref_text, encoding="utf-8"
            )
            logger.info(
                f"[VoiceRef] 写入默认 ref_text: {settings.voice_clone.default_ref_text[:30]}..."
            )
        logger.info(f"VoiceRefManager initialized: {self.refs_dir}")

    @property
    def active_path(self) -> Path:
        return settings.voice_clone.ref_audio

    @property
    def active_text_path(self) -> Path:
        return settings.voice_clone.ref_text_path

    def has_active(self) -> bool:
        return self.active_path.exists() and self.active_text_path.exists()

    def get_active_info(self) -> dict:
        if not self.has_active():
            return {"exists": False}
        stat = self.active_path.stat()
        text = (
            self.active_text_path.read_text(encoding="utf-8").strip()
            if self.active_text_path.exists()
            else ""
        )
        return {
            "exists": True,
            "filename": self.active_path.name,
            "text": text,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
        }

    async def upload(self, file: UploadFile) -> dict:
        """上传参考音频并设为 active；旧的归档到 history/。

        返回 { ok, filename, size_bytes, duration?, sample_rate? }
        """
        filename = file.filename or "audio.wav"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
        if ext not in ALLOWED_EXT:
            raise ValueError(
                f"不支持的格式：{ext}（允许: {', '.join(sorted(ALLOWED_EXT))}）"
            )

        # 1. 旧的归档
        self._archive_current()

        # 2. 落盘到临时路径
        ts = int(time.time() * 1000)
        tmp_path = self.refs_dir / f"voice_{ts}.{ext}"
        content = await file.read()
        if len(content) > settings.voice_clone.upload_max_bytes:
            raise ValueError(
                f"音频过大（{len(content)} bytes），"
                f"上限 {settings.voice_clone.upload_max_bytes} bytes"
            )
        tmp_path.write_bytes(content)

        # 3. 转 wav（如果非 wav）
        if ext != "wav":
            wav_path = self._to_wav(tmp_path)
            if wav_path is None:
                logger.warning(
                    f"ffmpeg 转 wav 失败，保留原文件 {tmp_path}（克隆质量可能下降）"
                )
                final_path = tmp_path.with_suffix(".wav")
                shutil.move(str(tmp_path), str(final_path))
            else:
                tmp_path.unlink(missing_ok=True)
                final_path = wav_path
        else:
            final_path = tmp_path.with_suffix(".wav")
            shutil.move(str(tmp_path), str(final_path))

        # 4. 覆盖 active
        if self.active_path.exists():
            self.active_path.unlink()
        shutil.move(str(final_path), str(self.active_path))

        stat = self.active_path.stat()
        result = {
            "ok": True,
            "filename": self.active_path.name,
            "size_bytes": stat.st_size,
        }

        # 用 soundfile 读元信息（可选）
        try:
            import soundfile as sf

            info = sf.info(str(self.active_path))
            result["duration_sec"] = round(float(info.duration), 2)
            result["sample_rate"] = int(info.samplerate)
            result["channels"] = int(info.channels)
        except Exception as e:
            logger.debug(f"读取音频元信息失败（不影响上传）: {e}")

        logger.info(f"Voice ref uploaded: {result}")
        return result

    def set_ref_text(self, text: str) -> dict:
        """设置 active 参考文本（F5-TTS 必须）。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("ref_text 不能为空")
        self.active_text_path.parent.mkdir(parents=True, exist_ok=True)
        self.active_text_path.write_text(text, encoding="utf-8")
        logger.info(f"Voice ref text set: {text[:60]}...")
        return {"ok": True, "text": text}

    def delete_active(self) -> dict:
        if self.active_path.exists():
            self.active_path.unlink()
        if self.active_text_path.exists():
            self.active_text_path.unlink()
        return {"ok": True}

    def list_history(self) -> list[dict]:
        items = []
        for p in sorted(self.history_dir.glob("voice_*"), reverse=True):
            stat = p.stat()
            txt = p.with_suffix(".txt")
            items.append(
                {
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                    "has_text": txt.exists(),
                }
            )
        return items

    # ============ 内部 ============

    def _archive_current(self):
        """把当前 active 文件归档到 history/。"""
        ts = int(time.time() * 1000)
        if self.active_path.exists():
            shutil.copy2(
                self.active_path, self.history_dir / f"voice_{ts}.wav"
            )
        if self.active_text_path.exists():
            shutil.copy2(
                self.active_text_path, self.history_dir / f"voice_{ts}.txt"
            )

    @staticmethod
    def _to_wav(src: Path) -> Optional[Path]:
        """调用 ffmpeg 转 24kHz mono s16 wav。失败返回 None。"""
        import subprocess

        wav_target = src.with_suffix(".wav")
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-sample_fmt",
                    "s16",
                    str(wav_target),
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if proc.returncode == 0 and wav_target.exists():
                return wav_target
            logger.warning(
                f"ffmpeg 转 wav 失败: {proc.stderr.decode()[:200]}"
            )
        except Exception as e:
            logger.warning(f"ffmpeg 调用失败: {e}")
        return None


# 全局单例
voice_ref_manager = VoiceRefManager()