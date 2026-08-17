from avs.config import load_profile
from avs.media.mix import loudnorm_filter, mix_filter
from avs.media.timeline import narration_spans, scene_length_for_narration
from avs.models import AmbientMode


def test_clip_length_is_driven_by_narration():
    """2-pass의 핵심: 목소리 길이가 화면 길이를 정한다."""
    requested, target = scene_length_for_narration(
        6.2, head_pad=0.35, tail_pad=0.5, max_seconds=15
    )
    # 6.2 + 0.35 + 0.5 = 7.05 → 백엔드는 정수 초만 받으므로 8초를 요청하고
    assert requested == 8
    # 타임라인에서는 7.05초만 쓴다 (올림 때문에 생기는 빈 화면 0.95초 제거)
    assert abs(target - 7.05) < 0.001


def test_requested_is_always_at_least_target():
    for narration in (1.0, 3.3, 6.2, 9.9, 12.4):
        requested, target = scene_length_for_narration(
            narration, head_pad=0.35, tail_pad=0.5, max_seconds=15
        )
        assert requested >= target - 0.001, (narration, requested, target)


def test_short_narration_respects_minimum():
    requested, target = scene_length_for_narration(
        0.1, head_pad=0.0, tail_pad=0.0, max_seconds=15, min_seconds=1.0
    )
    assert requested == 1
    assert target == 1.0


def test_overlong_narration_is_clamped_to_backend_limit():
    # 백엔드가 15초까지만 만들 수 있으므로 그 이상은 요청하지 않는다.
    requested, target = scene_length_for_narration(
        30.0, head_pad=0.35, tail_pad=0.5, max_seconds=15
    )
    assert requested == 15
    assert target == 15.0


def test_subtitles_follow_the_voice_not_the_scene():
    scene_durations = [8.0, 8.0]
    narration_durations = [5.0, 6.0]
    spans = narration_spans(
        scene_durations, narration_durations, head_pad=0.35, transition=0.0
    )
    # 씬은 0초에 시작하지만 자막은 말이 시작하는 0.35초부터
    assert spans[0] == (0.35, 5.35)
    assert spans[1] == (8.35, 14.35)


def test_subtitle_span_never_runs_past_its_scene():
    # 내레이션이 화면보다 길면 자막을 씬 끝에서 끊는다
    spans = narration_spans([5.0], [20.0], head_pad=0.35)
    assert spans[0][1] <= 5.0


def test_duck_filter_uses_narration_as_the_sidechain_key():
    profile = load_profile("shorts")
    assert profile.ambient is AmbientMode.DUCK
    graph = mix_filter(profile, 0.35)
    assert "adelay=350|350" in graph
    assert "asplit=2[nar][key]" in graph  # 같은 스트림을 믹스와 키로 두 번 쓴다
    assert "sidechaincompress" in graph
    assert graph.endswith("[aout]")


def test_duck_filter_pads_the_narration_so_ambient_is_not_cut_short():
    """sidechaincompress 는 먼저 끝나는 입력에서 멈춘다.

    내레이션은 클립보다 짧으므로 패딩이 없으면 씬 끝의 환경음이 잘려 나간다.
    """
    graph = mix_filter(load_profile("shorts"), 0.35)
    assert ",apad,asplit" in graph
    # 패딩은 딜레이 다음, 분기 전이어야 믹스와 키 양쪽에 적용된다
    assert graph.index("adelay") < graph.index("apad") < graph.index("asplit")


def test_every_ambient_mode_survives_a_narration_shorter_than_the_clip():
    for mode in AmbientMode:
        graph = mix_filter(load_profile("shorts").model_copy(update={"ambient": mode}), 0.35)
        # 짧은 내레이션이 출력 길이를 결정해서는 안 된다.
        # duck/mute 는 apad 로, attenuate 는 amix 의 first(=환경음)로 보장된다.
        assert "apad" in graph or "duration=first" in graph, mode


def test_attenuate_filter_uses_fixed_gain():
    profile = load_profile("shorts").model_copy(update={"ambient": AmbientMode.ATTENUATE})
    graph = mix_filter(profile, 0.35)
    assert "volume=-18.0dB" in graph
    assert "sidechaincompress" not in graph


def test_mute_filter_drops_the_ambient_input():
    profile = load_profile("shorts").model_copy(update={"ambient": AmbientMode.MUTE})
    graph = mix_filter(profile, 0.35)
    assert "[0:a]" not in graph
    assert graph.endswith("[aout]")


def test_loudnorm_targets_youtube():
    assert loudnorm_filter(-14.0) == "loudnorm=I=-14.0:TP=-1.5:LRA=11"


def test_profile_narration_defaults_are_wired():
    profile = load_profile("shorts")
    assert profile.narration.enabled
    assert profile.narration.model == "supertonic"
    assert profile.narration.pad == profile.narration.head_pad + profile.narration.tail_pad
    assert profile.max_scene_duration == 15.0
