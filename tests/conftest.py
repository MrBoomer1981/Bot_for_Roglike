"""Общие приспособления для тестов."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from balatro_bot.adapters.mod_bridge import ModBridge
from tests.fake_mod import running_fake_mod


@pytest.fixture
def fake_mod_port() -> Iterator[int]:
    """Порт поднятого фальшивого мода."""
    with running_fake_mod() as port:
        yield port


@pytest.fixture
def bridge(fake_mod_port: int) -> ModBridge:
    """Мост, подключённый к фальшивому моду."""
    return ModBridge(port=fake_mod_port, timeout=5.0)
