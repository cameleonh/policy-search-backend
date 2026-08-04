"""Shared pytest fixtures for database migration tests.

In CI, DATABASE_URL is pre-set pointing to a GitHub Actions service
container.  Locally, the fixture spins up a temporary Docker container.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text


def _wait_for_port(host: str, port: int, timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    msg = f"Port {port} on {host} never became available"
    raise RuntimeError(msg)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def _wait_for_db(url: str, timeout: int = 30) -> None:
    engine = create_engine(url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return
        except Exception:
            time.sleep(1)
    engine.dispose()
    msg = "Postgres never became ready"
    raise RuntimeError(msg)


@pytest.fixture(scope="session")
def db_url() -> Generator[str, None, None]:
    """Provide a DATABASE_URL — from env (CI) or a local Docker container."""
    existing = os.environ.get("DATABASE_URL")
    if existing:
        _wait_for_db(existing)
        yield existing
        return

    # Local: spin up a temporary container
    port = _find_free_port()
    container_name = "policy-search-test-pg"

    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            "POSTGRES_USER=policy",
            "-e",
            "POSTGRES_PASSWORD=policy",
            "-e",
            "POSTGRES_DB=policy_search",
            "-p",
            f"{port}:5432",
            "pgvector/pgvector:pg16",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = f"Failed to start postgres container: {result.stderr}"
        raise RuntimeError(msg)

    try:
        _wait_for_port("127.0.0.1", port)
        url = f"postgresql+psycopg://policy:policy@127.0.0.1:{port}/policy_search"
        _wait_for_db(url)
        os.environ["DATABASE_URL"] = url
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    """Apply all Alembic migrations to the test database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")
    return db_url
