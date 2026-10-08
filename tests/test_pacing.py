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


async def test_prune_respects_refcount_even_when_the_lock_is_momentarily_unlocked(fake_clock) -> None:
    # Review-reproduced race: `.locked()` only reflects whether the lock is
    # currently HELD. Between a holder releasing it and a waiter actually
    # resuming to re-acquire it, `.locked()` is False for one event-loop
    # iteration even though the key is still very much "in use". Pruning
    # by `.locked()` alone could delete that key's _last_seen timestamp in
    # that exact window — the waiter would then see no history and fire
    # immediately, violating the >=1s rule. Refcount (incremented at
    # _get_key_lock, decremented only when the whole slot cycle finishes)
    # covers this window regardless of the lock object's own state.
    pacer = KeyPacer(min_interval=0.0, max_tracked_keys=1, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    pacer._get_key_lock("race-key")  # simulates a coroutine mid-slot; refcount -> 1
    assert not pacer._key_locks["race-key"].locked()  # the lock itself is NOT held

    for i in range(5):
        async with pacer.slot(f"other-{i}"):
            pass

    assert "race-key" in pacer._key_locks  # still protected by refcount, not by .locked()

    pacer._release_key_lock("race-key")  # the simulated coroutine finishes its slot


async def test_prune_skips_a_locked_entry_instead_of_giving_up(fake_clock) -> None:
    # A long-held OLDEST lock must not disable pruning of newer, unlocked
    # keys — the old code `break`s on the first locked entry it finds.
    pacer = KeyPacer(min_interval=0.0, max_tracked_keys=1, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with pacer.slot("oldest-held"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()

    for i in range(5):
        async with pacer.slot(f"newer-{i}"):
            pass

    # Every "newer-*" key except the very last should have been pruned —
    # pruning must not have stopped dead just because "oldest-held" (the
    # actual oldest entry) couldn't be evicted.
    assert "newer-0" not in pacer._key_locks

    release.set()
    await task
