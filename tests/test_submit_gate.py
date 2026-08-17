import threading
import time

from avs.stages.s3_clips import SubmitGate


def test_gate_spaces_out_sequential_calls():
    gate = SubmitGate(0.05)
    start = time.monotonic()
    for _ in range(4):
        gate.wait()
    elapsed = time.monotonic() - start
    # 첫 호출은 즉시 통과하므로 최소 3구간만큼은 걸려야 한다.
    assert elapsed >= 0.15


def test_gate_spaces_out_concurrent_calls():
    """동시에 몰려도 실제 통과 시각은 최소 간격만큼 벌어져야 한다."""
    gate = SubmitGate(0.05)
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
    assert all(gap >= 0.04 for gap in gaps), gaps
