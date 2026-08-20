import threading
import time

from avs.stages.s3_clips import SubmitGate

INTERVAL = 0.05

#: 시계 여유 (간격의 80%).
#:
#: Windows의 타이머 해상도(약 15.6ms) 때문에 `time.sleep` 이 요청보다 조금 일찍
#: 깬다. 실측으로 3구간 150ms가 140ms로 측정되는 일이 흔했다. 게이트가 도는지를
#: 보는 테스트지 시계 정확도를 재는 게 아니므로 여유를 둔다. 게이트가 아예 안
#: 돌면 경과 시간이 0에 가까우니 이 여유로도 여전히 잡힌다.
SLACK = 0.8


def test_gate_spaces_out_sequential_calls():
    gate = SubmitGate(INTERVAL)
    start = time.monotonic()
    for _ in range(4):
        gate.wait()
    elapsed = time.monotonic() - start
    # 첫 호출은 즉시 통과하므로 최소 3구간만큼은 걸려야 한다.
    assert elapsed >= INTERVAL * 3 * SLACK, elapsed


def test_gate_spaces_out_concurrent_calls():
    """동시에 몰려도 실제 통과 시각은 최소 간격만큼 벌어져야 한다."""
    gate = SubmitGate(INTERVAL)
    stamps: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        gate.wait()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(gap >= INTERVAL * SLACK for gap in gaps), gaps


def test_gate_without_interval_does_not_block():
    """간격이 0이면 게이트는 아무것도 하지 않는다."""
    gate = SubmitGate(0.0)
    start = time.monotonic()
    for _ in range(10):
        gate.wait()
    assert time.monotonic() - start < INTERVAL
