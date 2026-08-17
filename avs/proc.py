"""외부 프로세스 실행 헬퍼.

ffmpeg, claude, codex, hermes 를 모두 이걸로 돌린다. Windows 콘솔 기본
인코딩(cp949) 때문에 한글이 깨지는 걸 막으려고 UTF-8 디코딩을 강제한다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class CommandFailed(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        tail = stderr.strip().splitlines()[-25:]
        super().__init__(
            f"명령 실패 (exit {returncode}): {cmd[0]}\n" + "\n".join(tail)
        )


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run(
    cmd: list[str],
    *,
    timeout: float | None = None,
    cwd: Path | None = None,
    stdin: str | None = None,
    check: bool = True,
    log_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        proc = subprocess.run(  # noqa: S603 - 인자는 전부 코드가 구성한다
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandFailed(cmd, -1, f"{timeout}초 안에 끝나지 않았습니다: {exc}") from exc

    result = CommandResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ {' '.join(cmd)}\n\n--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n",
            encoding="utf-8",
        )

    if check and result.returncode != 0:
        raise CommandFailed(cmd, result.returncode, result.stderr or result.stdout)
    return result
