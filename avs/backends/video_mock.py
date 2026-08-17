"""오프라인 개발용 가짜 영상 백엔드.

계정·구독·네트워크 없이 파이프라인 전체를 관통시키기 위한 것.

실제 백엔드(xAI Grok Imagine)처럼 720p 소스를, 요청한 비율로 낸다.
캔버스보다 작게 나오므로 mock 실행만으로도 정규화의 업스케일 경로가 검증된다.

오디오는 일부러 넣지 않는다. 실제 Grok 클립에는 환경음이 들어 있어서
정규화가 원본 오디오를 그대로 쓰는 쪽 경로를 타는데, mock이 무음이면
반대쪽(무음 트랙을 채워 넣는) 경로가 덮인다. 두 경로가 이렇게 나눠 커버된다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import config
from ..proc import CommandFailed, run
from .base import BackendError, VideoGenRequest

# 씬마다 다른 색이 나오게 해서 concat 순서를 눈으로 확인할 수 있게 한다.
_PALETTE = [
    "0x1f3a5f", "0x5f1f3a", "0x3a5f1f", "0x5f4a1f",
    "0x1f5f5a", "0x4a1f5f", "0x5f2f2f", "0x2f5f3f",
]

_RESOLUTION_SHORT_SIDE = {"480p": 480, "720p": 720}


def source_size(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    """xAI가 낼 법한 소스 크기를 계산한다. 짧은 변이 해상도 등급을 따른다."""
    short = _RESOLUTION_SHORT_SIDE.get(resolution, 720)
    try:
        a, b = (int(x) for x in aspect_ratio.split(":"))
    except ValueError:
        a, b = 16, 9
    if a >= b:  # 가로
        height = short
        width = round(short * a / b)
    else:  # 세로
        width = short
        height = round(short * b / a)
    # 인코더가 싫어하므로 짝수로 맞춘다.
    return width - width % 2, height - height % 2


class MockVideoBackend:
    name = "mock"

    def generate(self, request: VideoGenRequest) -> Path:
        out = request.out_path
        out.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha1(request.prompt.encode("utf-8")).hexdigest()
        colour = _PALETTE[int(digest[:2], 16) % len(_PALETTE)]
        width, height = source_size(request.aspect_ratio, request.resolution)
        duration = request.duration
        label = out.stem.replace("_", " ").upper()

        base_cmd = [
            config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c={colour}:s={width}x{height}:r=30:d={duration}",
        ]
        tail = [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "veryfast",
            "-an",  # 실제 Grok 클립과 마찬가지로 무음
            str(out),
        ]

        # drawtext는 폰트 환경을 타서 실패할 수 있다. 라벨은 있으면 좋은 것일
        # 뿐이므로, 실패하면 색만 있는 클립으로 물러선다.
        # 필터 문자열의 Windows 경로 이스케이프를 피하려고 cwd를 옮기고
        # 상대 파일명만 쓴다.
        textfile = out.parent / f".{out.stem}.label.txt"
        textfile.write_text(label, encoding="utf-8")
        drawtext = (
            f"drawtext=textfile={textfile.name}:fontcolor=white:fontsize=72"
            ":x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.4:boxborderw=20"
        )
        try:
            run(base_cmd + ["-vf", drawtext] + tail, cwd=out.parent, timeout=120)
        except CommandFailed:
            try:
                run(base_cmd + tail, timeout=120)
            except CommandFailed as exc:
                raise BackendError(f"mock 클립 생성 실패: {exc}", retryable=False) from exc
        finally:
            textfile.unlink(missing_ok=True)

        if not out.is_file() or out.stat().st_size == 0:
            raise BackendError("mock 클립이 만들어지지 않았습니다", retryable=False)
        return out
