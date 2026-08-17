"""파이프라인 전체가 공유하는 데이터 계약.

여기 정의된 모델이 스테이지 간 유일한 인터페이스다. 스테이지는 서로를 직접
호출하지 않고 `RunManifest` + 디스크 산출물만 통해 이어진다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FitMode(str, Enum):
    """소스 클립을 프로파일 캔버스에 맞추는 방식."""

    COVER = "cover"  # 캔버스를 꽉 채우고 넘치는 부분은 크롭
    CONTAIN = "contain"  # 전체를 보존하고 남는 부분은 레터박스


class Transition(str, Enum):
    NONE = "none"
    XFADE = "xfade"


class AmbientMode(str, Enum):
    """내레이션이 있을 때 클립에 딸려온 환경음을 어떻게 다룰지."""

    DUCK = "duck"  # 말하는 동안만 눌러준다 (사이드체인). 가장 자연스럽다
    ATTENUATE = "attenuate"  # 고정 감쇠. 예측 가능하고 디버깅이 쉽다
    MUTE = "mute"  # 환경음을 버린다


class SourceAudio(str, Enum):
    """생성된 클립에 딸려오는 오디오를 어떻게 할지.

    Grok Imagine 클립에는 프롬프트에 맞는 환경음이 들어 있다. B롤로는
    분위기를 살려주지만 내레이션과 겹치면 지저분해진다.
    """

    KEEP = "keep"  # 그대로 둔다
    MUTE = "mute"  # 무음 트랙으로 갈아끼운다 (Vrew에서 목소리만 얹을 때)


class SubtitleStyle(BaseModel):
    """ffmpeg ASS 자막 스타일. Vrew 경로에서는 사용하지 않는다."""

    font_name: str = "Malgun Gothic"
    font_size: int = 64
    primary_colour: str = "&H00FFFFFF"  # ASS는 &HAABBGGRR (AA=00이 불투명)
    outline_colour: str = "&H00000000"
    back_colour: str = "&H80000000"
    bold: bool = True
    outline: int = 3
    shadow: int = 0
    border_style: int = 1  # 1=아웃라인+그림자, 3=불투명 박스
    alignment: int = 2  # numpad 배치: 2=하단 중앙
    margin_v: int = 160


class NarrationConfig(BaseModel):
    """내레이션 합성 설정.

    `backend: none` 이면 내레이션 단계를 통째로 건너뛴다 — 예전처럼 씬 길이가
    고정되고 목소리는 Vrew에서 입힌다.
    """

    backend: str = "local"  # local | none
    model: str = "supertonic"
    voice: str | None = "F1"
    #: 클로닝용. Supertonic은 이 값을 Voice Builder 스타일 JSON 경로로 읽는다.
    reference_audio: str | None = None
    speed: float = 1.0
    #: None이면 어댑터 기본값. Supertonic은 'na'(멀티링구얼)라서
    #: 한국어에 영어가 섞여 있어도 그대로 넘길 수 있다.
    language: str | None = None

    #: 말이 클립 경계에 붙어 잘리지 않도록 앞뒤로 두는 여유.
    head_pad: float = 0.35
    tail_pad: float = 0.5

    @property
    def enabled(self) -> bool:
        return self.backend != "none"

    @property
    def pad(self) -> float:
        return self.head_pad + self.tail_pad


class Profile(BaseModel):
    """출력 포맷 정의. 쇼츠/롱폼 분기를 코드가 아니라 이 설정으로 처리한다."""

    name: str
    width: int
    height: int
    fps: int = 30

    # 씬 하나의 목표 길이. 내레이션을 쓰면 **고정값이 아니라 대본 작성용
    # 목표치**다 — 실제 클립 길이는 합성된 내레이션 길이가 정한다(2-pass).
    # 내레이션을 끄면(narration.backend=none) 예전처럼 고정 길이로 쓰인다.
    scene_duration: float = 8.0
    #: 영상 생성 백엔드가 받아주는 클립 길이 상한 (Grok Imagine은 15초).
    max_scene_duration: float = 15.0
    min_scenes: int = 5
    max_scenes: int = 8

    # 영상 생성 백엔드에 그대로 넘기는 요청값. 캔버스와 맞춰두면 정규화
    # 단계에서 크롭으로 화면을 버리는 일이 없다.
    aspect_ratio: str = "16:9"
    source_resolution: str = "720p"  # xAI는 480p/720p만 지원

    # 한국어 내레이션 속도(음절/초). scene_duration과 곱해 씬별 글자수 상한을
    # 만든다. 낭독 여유를 두고 보수적으로 잡는다.
    chars_per_second: float = 4.0
    #: 지정하면 계산값 대신 이 값을 상한으로 쓴다.
    narration_max_chars: int | None = None

    fit: FitMode = FitMode.COVER
    source_audio: SourceAudio = SourceAudio.KEEP
    narration: NarrationConfig = Field(default_factory=NarrationConfig)
    ambient: AmbientMode = AmbientMode.DUCK
    #: `ambient: attenuate` 일 때 환경음에 걸 고정 감쇠.
    ambient_gain_db: float = -18.0
    #: 최종 라우드니스 (LUFS). 유튜브 기준이 -14. None이면 손대지 않는다.
    loudness_target: float | None = -14.0
    transition: Transition = Transition.NONE
    transition_duration: float = 0.4

    video_codec: str = "libx264"
    crf: int = 20
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 48000

    subtitles: SubtitleStyle = Field(default_factory=SubtitleStyle)

    # s1/s2 프롬프트에 그대로 주입되는 자유 서술. 톤·구성 지침.
    style_notes: str = ""

    @property
    def aspect_label(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def target_duration(self) -> float:
        return self.scene_duration * self.max_scenes

    @property
    def effective_transition(self) -> float:
        """실제로 적용되는 겹침 길이.

        `transition: none` 인데도 `transition_duration` 을 타임라인 계산에
        쓰면 자막이 씬마다 조금씩 앞당겨져 누적으로 크게 어긋난다.
        """
        if self.transition is Transition.XFADE:
            return self.transition_duration
        return 0.0

    @property
    def narration_limit(self) -> int:
        """씬 하나의 내레이션 글자수 상한."""
        if self.narration_max_chars is not None:
            return self.narration_max_chars
        return max(10, int(self.scene_duration * self.chars_per_second))


class Scene(BaseModel):
    """대본의 최소 단위. 클립 1개와 1:1 대응한다."""

    index: int  # 1-based
    narration: str
    video_prompt: str
    on_screen_text: str = ""

    @property
    def slug(self) -> str:
        return f"scene_{self.index:02d}"


class Script(BaseModel):
    title: str
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)

    def scene(self, index: int) -> Scene:
        for s in self.scenes:
            if s.index == index:
                return s
        raise KeyError(f"씬 {index}가 대본에 없습니다")


class SceneArtifact(BaseModel):
    """씬 하나의 생성 결과. 씬 단위 재시도/재생성의 근거가 된다."""

    index: int
    status: StageStatus = StageStatus.PENDING
    clip_path: str | None = None
    normalized_path: str | None = None
    duration: float | None = None
    #: 영상 백엔드에 요청한 길이(정수 초). 백엔드가 정수만 받는다.
    clip_request_seconds: int | None = None
    #: 타임라인에서 이 씬이 차지해야 할 정확한 길이. 정규화 단계가 여기로 자른다.
    target_seconds: float | None = None
    attempts: int = 0
    backend: str | None = None
    error: str | None = None
    updated_at: str = Field(default_factory=utcnow)


class NarrationArtifact(BaseModel):
    """씬 하나의 내레이션 오디오.

    `text_sha` 가 재개의 핵심이다. 대본을 고쳐 문장이 바뀐 씬만 다시 합성하고
    손대지 않은 씬은 건드리지 않는다.
    """

    index: int
    status: StageStatus = StageStatus.PENDING
    path: str | None = None
    #: 앞뒤 무음을 잘라낸 뒤의 길이. 타임라인이 쓰는 값이다.
    duration: float | None = None
    #: TTS가 처음 낸 길이 (무음 포함). 진단용.
    raw_duration: float | None = None
    #: 잘라낸 선행 무음 길이. 진단용.
    lead_trimmed: float | None = None
    text_sha: str | None = None
    spoken_text: str | None = None  # 정규화를 거친, 실제로 모델에 넣은 문장
    voice: str | None = None
    model: str | None = None
    attempts: int = 0
    error: str | None = None
    updated_at: str = Field(default_factory=utcnow)


class StageState(BaseModel):
    status: StageStatus = StageStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)


class RunManifest(BaseModel):
    """실행 하나의 단일 진실 원천.

    모든 스테이지는 멱등이다. 실행 전에 이 매니페스트를 보고 이미 완료된
    스테이지는 건너뛴다. 영상 생성이 느리고 자주 깨지기 때문에, 재개
    가능성이 부가 기능이 아니라 기본 전제다.
    """

    schema_version: int = 1
    run_id: str
    topic: str
    profile_name: str
    profile: Profile
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)

    video_backend: str = "mock"
    llm_backend: str = "claude"
    skip_vrew: bool = False

    stages: dict[str, StageState] = Field(default_factory=dict)
    scenes: dict[str, SceneArtifact] = Field(default_factory=dict)
    narrations: dict[str, NarrationArtifact] = Field(default_factory=dict)
    notes: dict[str, Any] = Field(default_factory=dict)

    def stage(self, name: str) -> StageState:
        return self.stages.setdefault(name, StageState())

    def scene_artifact(self, index: int) -> SceneArtifact:
        key = str(index)
        if key not in self.scenes:
            self.scenes[key] = SceneArtifact(index=index)
        return self.scenes[key]

    def narration_artifact(self, index: int) -> NarrationArtifact:
        key = str(index)
        if key not in self.narrations:
            self.narrations[key] = NarrationArtifact(index=index)
        return self.narrations[key]


class RunPaths:
    """실행 디렉터리 레이아웃. 경로 문자열을 코드 곳곳에 흩뿌리지 않기 위한 단일 지점."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def outline(self) -> Path:
        return self.root / "01_outline.md"

    @property
    def script(self) -> Path:
        return self.root / "02_script.json"

    @property
    def clips(self) -> Path:
        return self.root / "clips"

    @property
    def build(self) -> Path:
        return self.root / "build"

    @property
    def roughcut(self) -> Path:
        return self.build / "roughcut.mp4"

    @property
    def srt(self) -> Path:
        return self.build / "script.srt"

    @property
    def ass(self) -> Path:
        return self.build / "script.ass"

    @property
    def vrew_in(self) -> Path:
        return self.root / "vrew_in"

    @property
    def vrew_out(self) -> Path:
        return self.root / "vrew_out"

    @property
    def final(self) -> Path:
        return self.root / "final"

    @property
    def narration(self) -> Path:
        return self.root / "narration"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for d in (
            self.root,
            self.clips,
            self.narration,
            self.build,
            self.vrew_in,
            self.vrew_out,
            self.final,
            self.logs,
        ):
            d.mkdir(parents=True, exist_ok=True)
