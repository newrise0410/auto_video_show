from avs.media.silence import edge_silence, parse_silence_ranges, trim_bounds

# 실제 scene_01.wav 에서 나온 silencedetect 출력. 앞뒤뿐 아니라 문장 중간에도
# 끊김이 있어서, 가장자리만 골라내는지 확인하는 데 딱 맞는 표본이다.
REAL_LOG = """
[Parsed_silencedetect_0 @ 0x1] silence_start: 0
[Parsed_silencedetect_0 @ 0x1] silence_end: 0.631633 | silence_duration: 0.631633
[Parsed_silencedetect_0 @ 0x1] silence_start: 1.070703
[Parsed_silencedetect_0 @ 0x1] silence_end: 1.172721 | silence_duration: 0.102018
[Parsed_silencedetect_0 @ 0x1] silence_start: 1.685079
[Parsed_silencedetect_0 @ 0x1] silence_end: 1.799569 | silence_duration: 0.114490
[Parsed_silencedetect_0 @ 0x1] silence_start: 3.345828
[Parsed_silencedetect_0 @ 0x1] silence_end: 3.970612 | silence_duration: 0.624784
"""


def test_parse_pairs_starts_with_ends():
    ranges = parse_silence_ranges(REAL_LOG)
    assert len(ranges) == 4
    assert ranges[0] == (0.0, 0.631633)
    assert ranges[3] == (3.345828, 3.970612)


def test_unterminated_final_range_has_no_end():
    log = "silence_start: 0\nsilence_end: 0.5\nsilence_start: 2.9\n"
    ranges = parse_silence_ranges(log)
    assert ranges[-1] == (2.9, None)


def test_only_the_edges_count():
    """문장 중간의 끊김(1.07~1.17, 1.68~1.80)은 세면 안 된다."""
    lead, trail = edge_silence(parse_silence_ranges(REAL_LOG), 3.970612)
    assert abs(lead - 0.631633) < 0.001
    assert abs(trail - 0.624784) < 0.001


def test_unterminated_range_counts_as_trailing():
    ranges = [(0.0, 0.4), (2.9, None)]
    lead, trail = edge_silence(ranges, 3.5)
    assert lead == 0.4
    assert abs(trail - 0.6) < 0.001


def test_no_silence_means_no_trim():
    lead, trail = edge_silence([], 3.0)
    assert (lead, trail) == (0.0, 0.0)
    assert trim_bounds(0.0, 0.0, 3.0) is None


def test_trim_bounds_keeps_a_guard():
    # 앞 0.63 / 뒤 0.62 인 3.97초 파일 → 0.03초 여유를 남기고 자른다
    start, duration = trim_bounds(0.631633, 0.624784, 3.970612, guard=0.03)
    assert abs(start - 0.602) < 0.001
    assert abs(duration - (3.970612 - 0.624784 + 0.03 - 0.602)) < 0.002
    # 실제 발화 구간(0.63~3.35)을 전부 품어야 한다
    assert start <= 0.631633
    assert start + duration >= 3.345828


def test_all_silence_is_left_alone():
    """전부 무음인 파일을 잘라내면 아무것도 안 남는다. 손대지 않는다."""
    assert trim_bounds(3.0, 3.0, 3.0) is None


def test_almost_all_silence_is_left_alone():
    assert trim_bounds(1.9, 1.0, 3.0) is None  # 남는 게 0.2초 미만


def test_realistic_case_saves_over_a_second():
    """scene_03: 3.76초 중 실제 발화는 약 2.4초뿐이었다."""
    bounds = trim_bounds(0.614331, 0.754649, 3.761633)
    assert bounds is not None
    _, duration = bounds
    assert 2.3 < duration < 2.6
