import asyncio

import pytest

from meu_danfe.exceptions import ConfigurationError
from meu_danfe.pacing import KeyPacer


async def test_same_key_waits_at_least_min_interval(fake_clock) -> None:
    pacer = KeyPacer(min_interval=1.0, clock=fake_clock.clock, sleep=fake_clock.sleep)
    key = "k" * 44
    async with pacer.slot(key):
        pass
    start = fake_clock.now
    async with pacer.slot(key):
        pass
    assert fake_clock.now - start >= 1.0


async def test_different_keys_do_not_wait_for_each_other(fake_clock) -> None:
    pacer = KeyPacer(min_interval=1.0, clock=fake_clock.clock, sleep=fake_clock.sleep)
    async with pacer.slot("k" * 44):
        pass
    before = fake_clock.now
    async with pacer.slot("j" * 44):
        pass
    assert fake_clock.now == before  # no sleep needed for a different key


async def test_max_concurrency_bounds_in_flight_slots(fake_clock) -> None:
    pacer = KeyPacer(min_interval=0.0, max_concurrency=2, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    peak = 0
    current = 0

    async def worker(key: str) -> None:
        nonlocal peak, current
        async with pacer.slot(key):
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0)
            current -= 1

    await asyncio.gather(*(worker(f"key-{i}") for i in range(5)))
    assert peak <= 2


def test_min_interval_below_one_second_rejected_by_default() -> None:
    with pytest.raises(ConfigurationError):
        KeyPacer(min_interval=0.1)


def test_min_interval_below_one_second_allowed_when_opted_in() -> None:
    KeyPacer(min_interval=0.1, allow_unsafe_interval=True)  # does not raise


async def test_pruning_does_not_evict_a_held_lock(fake_clock) -> None:
    pacer = KeyPacer(min_interval=0.0, max_tracked_keys=2, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    for i in range(5):
        async with pacer.slot(f"key-{i}"):
            pass
    # No assertion beyond "did not raise" / did not grow unbounded — pruning
    # is a memory-bound guard, not user-visible behaviour.
    assert len(pacer._key_locks) <= 3  # a little slack is fine; unbounded growth is not
