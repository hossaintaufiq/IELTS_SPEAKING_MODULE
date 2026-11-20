import asyncio
import unittest

from session_guard import GuardConfig, SessionGuard


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_guard(**kwargs):
    clock = FakeClock()
    hung = []

    async def hangup(call_id):
        hung.append(call_id)

    guard = SessionGuard(hangup=hangup, config=GuardConfig(**kwargs), clock=clock)
    return guard, clock, hung


class SessionGuardTests(unittest.TestCase):
    def test_hangs_up_after_max_duration(self):
        guard, clock, hung = make_guard(max_session_s=900, idle_timeout_s=10_000)
        guard.admit("a", "u1", 1)
        clock.t = 899
        self.assertEqual(asyncio.run(guard.sweep()), [])
        clock.t = 900
        self.assertEqual(asyncio.run(guard.sweep()), [("a", "max_duration")])
        self.assertEqual(hung, ["a"])
        self.assertNotIn("a", guard.sessions)

    def test_idle_session_is_closed_but_active_one_is_kept(self):
        guard, clock, hung = make_guard(idle_timeout_s=60)
        guard.admit("idle", "u1", 1)
        guard.admit("busy", "u2", 1)
        clock.t = 50
        guard.touch("busy")
        clock.t = 70
        self.assertEqual(asyncio.run(guard.sweep()), [("idle", "idle")])
        self.assertEqual(hung, ["idle"])
        self.assertIn("busy", guard.sessions)

    def test_daily_limit_per_user(self):
        guard, _, _ = make_guard(max_sessions_per_user_per_day=2)
        self.assertTrue(guard.admit("a", "u1", 5)[0])
        self.assertTrue(guard.admit("b", "u1", 5)[0])
        self.assertEqual(guard.admit("c", "u1", 5), (False, "daily_limit"))
        self.assertTrue(guard.admit("d", "u1", 6)[0])
        self.assertTrue(guard.admit("e", "u2", 5)[0])

    def test_total_concurrency_cap(self):
        guard, _, _ = make_guard(max_concurrent_total=2)
        guard.admit("a", "u1", 1)
        guard.admit("b", "u2", 1)
        self.assertEqual(guard.admit("c", "u3", 1), (False, "capacity"))
        guard.release("a")
        self.assertTrue(guard.admit("c", "u3", 1)[0])

    def test_rejected_attempt_does_not_consume_daily_quota(self):
        guard, _, _ = make_guard(max_concurrent_total=1, max_sessions_per_user_per_day=2)
        guard.admit("a", "u1", 1)
        self.assertEqual(guard.admit("b", "u2", 1), (False, "capacity"))
        guard.release("a")
        self.assertTrue(guard.admit("c", "u2", 1)[0])
        guard.release("c")
        self.assertTrue(guard.admit("d", "u2", 1)[0])
        guard.release("d")
        self.assertEqual(guard.admit("e", "u2", 1), (False, "daily_limit"))


if __name__ == "__main__":
    unittest.main()
