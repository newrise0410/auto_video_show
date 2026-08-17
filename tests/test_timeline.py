from avs.media.timeline import scene_timings, total_duration, xfade_offsets


def test_no_transition_is_plain_cumulative():
    durations = [8.0, 8.0, 6.0]
    assert scene_timings(durations, 0.0) == [(0.0, 8.0), (8.0, 16.0), (16.0, 22.0)]
    assert total_duration(durations, 0.0) == 22.0


def test_transition_pulls_each_scene_earlier():
    durations = [8.0, 8.0, 8.0]
    timings = scene_timings(durations, 0.5)
    # i번째 씬은 i * 0.5초만큼 앞당겨진다.
    assert timings[0][0] == 0.0
    assert timings[1][0] == 7.5
    assert timings[2][0] == 15.0
    # 자막이 겹치지 않도록 각 씬의 끝은 다음 씬의 시작에 붙는다.
    assert timings[0][1] == timings[1][0]
    assert timings[1][1] == timings[2][0]
    assert total_duration(durations, 0.5) == 23.0
    assert timings[-1][1] == total_duration(durations, 0.5)


def test_uneven_durations_stay_aligned():
    durations = [4.0, 10.0, 6.5]
    timings = scene_timings(durations, 0.0)
    assert [round(s, 3) for s, _ in timings] == [0.0, 4.0, 14.0]
    assert timings[-1][1] == 20.5


def test_xfade_offsets_track_accumulated_output():
    durations = [8.0, 8.0, 8.0]
    assert xfade_offsets(durations, 0.5) == [7.5, 15.0]


def test_edge_cases():
    assert scene_timings([], 0.5) == []
    assert xfade_offsets([5.0], 0.5) == []
    assert total_duration([], 0.5) == 0.0
