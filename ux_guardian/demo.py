"""Cross-platform developer tooling. No shell scripts or paid agent calls."""

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import typer

from ux_guardian.security import redact

app = typer.Typer(help="Run and verify the demo locally.")
ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo-app"


def next_command(*args: str) -> list[str]:
    node = shutil.which("node")
    entry = DEMO / "node_modules" / "next" / "dist" / "bin" / "next"
    if node is None or not entry.exists():
        raise typer.BadParameter("Install Node and run pnpm install in demo-app first.")
    return [node, str(entry), *args]


@app.command()
def serve(port: int = 3000) -> None:
    """Run the demo in development; TEST_EMAIL/TEST_PASSWORD come from env or .env."""
    result = subprocess.run(
        next_command("dev", "--hostname", "127.0.0.1", "--port", str(port)), cwd=DEMO, check=False
    )
    raise typer.Exit(result.returncode)


@app.command()
def smoke(unseeded: bool = False) -> None:
    """Start a built demo with ephemeral credentials, test, and stop it."""
    if not (DEMO / ".next" / "BUILD_ID").exists():
        raise typer.BadParameter("Run pnpm build in demo-app before demo smoke.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["NEXT_TELEMETRY_DISABLED"] = "1"
    environment["UX_GUARDIAN_DEMO_URL"] = url
    environment["UX_GUARDIAN_DEMO_ARTIFACTS"] = str(ROOT / "artifacts" / "demo")
    if unseeded:
        environment.pop("TEST_EMAIL", None)
        environment.pop("TEST_PASSWORD", None)
        environment["UX_GUARDIAN_DEMO_UNSEEDED"] = "1"
    else:
        environment.pop("UX_GUARDIAN_DEMO_UNSEEDED", None)
        environment["TEST_EMAIL"] = f"demo-{secrets.token_hex(8)}@example.invalid"
        environment["TEST_PASSWORD"] = secrets.token_urlsafe(32)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        next_command("start", "--hostname", "127.0.0.1", "--port", str(port)),
        cwd=DEMO,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 30
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Demo exited before becoming ready; run pnpm start to inspect."
                    )
                try:
                    if client.get(url).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Demo did not become ready within 30 seconds.")
        targets = ["tests/test_demo_unseeded.py"] if unseeded else ["tests"]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *targets],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = result.stdout + result.stderr
        # Redact both inherited secrets and ephemeral credentials before displaying
        # captured pytest output, including exception details.
        for name in ("TEST_EMAIL", "TEST_PASSWORD"):
            if environment.get(name):
                output = output.replace(environment[name], "[REDACTED]")
        typer.echo(redact(output))
        raise typer.Exit(result.returncode)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
