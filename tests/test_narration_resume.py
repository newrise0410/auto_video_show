from avs.models import NarrationArtifact, StageStatus
from avs.stages.s_narrate import text_sha


def artifact(tmp_path, text: str, *, raw_duration: float | None = 3.9) -> NarrationArtifact:
    wav = tmp_path / "scene_01.wav"
    wav.write_bytes(b"\x00")
    return NarrationArtifact(
        index=1,
        status=StageStatus.COMPLETED,
        path=str(wav),
        duration=2.7,
        raw_duration=raw_duration,
        lead_trimmed=0.6,
        text_sha=text_sha(text),
    )


class FakeRun:
    """`_needs_synthesis` 는 매니페스트와 파일 존재만 본다."""

    def __init__(self, art: NarrationArtifact) -> None:
        self._art = art
        self.manifest = self

    def narration_artifact(self, index: int) -> NarrationArtifact:
        return self._art


class FakeScene:
    index = 1


def needs(art: NarrationArtifact, text: str, *, force: bool = False) -> bool:
    from avs.stages.s_narrate import _needs_synthesis

    return _needs_synthesis(FakeRun(art), FakeScene(), text, force=force)


def test_unchanged_text_is_reused(tmp_path):
    art = artifact(tmp_path, "원두 바꿔도 맛없다면")
    assert needs(art, "원두 바꿔도 맛없다면") is False


def test_changed_text_triggers_resynthesis(tmp_path):
    art = artifact(tmp_path, "원두 바꿔도 맛없다면")
    assert needs(art, "원두를 바꿔도 맛이 없다면") is True


def test_force_always_resynthesizes(tmp_path):
    art = artifact(tmp_path, "같은 문장")
    assert needs(art, "같은 문장", force=True) is True


def test_missing_file_triggers_resynthesis(tmp_path):
    art = artifact(tmp_path, "같은 문장")
    from pathlib import Path

    Path(art.path).unlink()
    assert needs(art, "같은 문장") is True


def test_pre_trim_artifacts_are_regenerated(tmp_path):
    """무음 다듬기 이전에 만들어진 산출물은 자막이 어긋나므로 다시 만든다.

    `raw_duration` 이 없다는 게 구버전이라는 신호다.
    """
    art = artifact(tmp_path, "같은 문장", raw_duration=None)
    assert needs(art, "같은 문장") is True
