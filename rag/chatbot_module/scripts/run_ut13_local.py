"""Run UT-13 with a temporary local DB and the existing real LLM/Qdrant settings."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            raise SystemExit("8000번 포트가 이미 사용 중입니다. 기존 서버를 종료한 뒤 실행하세요.")
    except (ConnectionRefusedError, TimeoutError):
        pass
    output_dir = root / "eval_outputs"
    output_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    # Some local terminals set this to an unwritable path; HTTPX then fails
    # while constructing its TLS context, before any benchmark request.
    env.pop("SSLKEYLOGFILE", None)
    # The encoder is already cached locally; skip Hugging Face metadata HEAD
    # requests so startup does not wait on an unavailable model hub.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["CHAT_DB_URL"] = "sqlite:///eval_outputs/ut13_measure.db"
    env["DB_AUTO_CREATE"] = "true"
    log_path = output_dir / "ut13_server.log"
    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [sys.executable, "-u", "main_dev.py"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        print(f"UT-13 서버 시작 중 (로그: {log_path})", flush=True)
        try:
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError(f"서버 시작 실패. 로그: {log_path}")
                try:
                    with urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError, OSError):
                    time.sleep(1)
            else:
                raise RuntimeError(f"서버 준비 시간 초과. 로그: {log_path}")
            return subprocess.call(
                [sys.executable, "scripts/measure_ut13.py", *sys.argv[1:]],
                cwd=root,
                env=env,
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
