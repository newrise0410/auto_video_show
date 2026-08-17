"""터미널 출력. 파이프라인이 길어서 지금 무엇을 하는지 계속 보여준다."""

from __future__ import annotations

from rich.console import Console

console = Console()


def step(message: str) -> None:
    console.print(f"[bold cyan]▶[/] {message}")


def ok(message: str) -> None:
    console.print(f"[bold green]✓[/] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]![/] {message}")


def fail(message: str) -> None:
    console.print(f"[bold red]✗[/] {message}")


def info(message: str) -> None:
    console.print(f"  [dim]{message}[/]")
