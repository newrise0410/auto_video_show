from pathlib import Path

from avs.backends.video_mock import source_size
from avs.config import load_profile, slugify
from avs.media.concat import build_xfade_graph
from avs.media.normalize import video_filter, wants_silent_track
from avs.media.probe import MediaInfo
from avs.models import FitMode, SourceAudio


def media(*, has_audio: bool) -> MediaInfo:
    return MediaInfo(
        path=Path("clip.mp4"),
        width=720,
        height=1280,
        duration=8.0,
        fps=24.0,
        has_audio=has_audio,
        has_video=True,
        codec="h264",
    )


def test_silent_track_is_added_only_when_needed():
    keep = load_profile("shorts")
    assert keep.source_audio is SourceAudio.KEEP
    # Grok 클립에는 환경음이 있으므로 원본을 그대로 쓴다.
    assert wants_silent_track(keep, media(has_audio=True)) is False
    # 트랙이 아예 없으면 채워 넣어야 concat에서 오디오가 사라지지 않는다.
    assert wants_silent_track(keep, media(has_audio=False)) is True


def test_mute_profile_replaces_existing_audio():
    mute = load_profile("shorts").model_copy(update={"source_audio": SourceAudio.MUTE})
    assert wants_silent_track(mute, media(has_audio=True)) is True


def test_cover_crops_to_fill_the_canvas():
    profile = load_profile("shorts")
    assert profile.fit is FitMode.COVER
    f = video_filter(profile)
    assert "force_original_aspect_ratio=increase" in f
    assert "crop=1080:1920" in f
    assert "flags=lanczos" in f  # 720p 소스를 1080으로 올린다
    assert "setsar=1" in f
    assert "fps=30" in f


def test_contain_pads_instead_of_cropping():
    profile = load_profile("shorts").model_copy(update={"fit": FitMode.CONTAIN})
    f = video_filter(profile)
    assert "force_original_aspect_ratio=decrease" in f
    assert "pad=1080:1920" in f
    assert "crop=" not in f


def test_mock_source_size_matches_requested_aspect():
    assert source_size("9:16", "720p") == (720, 1280)
    assert source_size("16:9", "720p") == (1280, 720)
    assert source_size("16:9", "480p") == (852, 480)
    assert source_size("1:1", "720p") == (720, 720)


def test_mock_source_size_is_always_even():
    for ratio in ("9:16", "16:9", "3:2", "2:3", "4:3"):
        w, h = source_size(ratio, "720p")
        assert w % 2 == 0 and h % 2 == 0


def test_xfade_graph_chains_video_and_audio():
    graph = build_xfade_graph([8.0, 8.0, 8.0], 0.5)
    assert "[0:v][1:v]xfade" in graph
    assert "offset=7.500" in graph
    assert "offset=15.000" in graph
    assert graph.endswith("[aout]")
    assert "[vout]" in graph


def test_slugify_keeps_hangul_and_drops_punctuation():
    assert slugify("테스트: 주제!") == "테스트-주제"
    assert slugify("  a b  ") == "a-b"
    assert slugify("???") == "untitled"
