"""Sprint 4 T6 — Per-check exception isolation regression-lock.

Without per-check try/except, ALL reminders abort if one raises. With per-check,
each reminder is independent. This file locks in the contract.
"""
import datetime as dt_mod
from unittest.mock import MagicMock, patch


class TestPerCheckExceptionIsolation:
    """test_reminder_2_failure_does_not_abort_reminders_1_3_4_5"""

    def test_reminder_2_failure_does_not_abort_reminders_1_3_4_5(self):
        """Mock 5 reminders; raise in reminder 2; assert reminders 3,4,5 still execute.

        Reminder 2 = Sunday review ritual (weekday==6, hour==17).
        We make notify_action_required raise on that specific call.
        With per-check try/except, reminders 3/4/5 still execute.
        Without it (function-wide except), all reminders after reminder 2 are aborted.
        """
        # "Sunday at 5PM" — triggers reminder 2 (Sunday review)
        sunday_5pm = dt_mod.datetime(2026, 5, 10, 17, 0, 0,
                                     tzinfo=dt_mod.timezone.utc)

        # call counter to sequence fetchone results
        call_count = [0]

        def fake_fetchone():
            call_count[0] += 1
            c = call_count[0]
            if c == 1:
                # reminder 1 milestone check: closed_count = 0 (skip milestone)
                r = MagicMock()
                r.__getitem__ = lambda self, key: 0
                return r
            elif c == 2:
                # reminder 1 already-notified check (for milestone 50 etc.)
                r = MagicMock()
                r.__getitem__ = lambda self, key: 0
                return r
            elif c == 3:
                # reminder 3 api_key_rotation: no last rotation row
                return None
            elif c == 4:
                # reminder 3 oldest_trade: old enough to trigger rotation reminder
                r = MagicMock()
                r.__getitem__ = lambda self, key: "2025-01-01T00:00:00"
                return r
            elif c == 5:
                # reminder 4 unscored training examples: >100 backlog
                r = MagicMock()
                r.__getitem__ = lambda self, key: 150
                return r
            elif c == 6:
                # reminder 5 retrain: active model with old created_at
                r = MagicMock()

                def getitem(self, key):
                    if key == "version_name":
                        return "halcyon-v1"
                    return "2025-01-01T00:00:00"

                r.__getitem__ = getitem
                return r
            else:
                r = MagicMock()
                r.__getitem__ = lambda self, key: 0
                return r

        fake_execute = MagicMock()
        fake_execute.fetchone.side_effect = fake_fetchone

        fake_conn = MagicMock()
        fake_conn.execute.return_value = fake_execute
        fake_conn.__enter__ = lambda s: fake_conn
        fake_conn.__exit__ = MagicMock(return_value=False)

        import src.notifications.telegram_commands as tc

        # notify_action_required is imported from telegram inside the function.
        # Patch it at the source module so the local import picks up the mock.
        def fake_notify(action, detail, urgency="normal"):
            if "review" in action.lower():
                # Deliberate failure in reminder 2
                raise RuntimeError("deliberate failure in reminder 2 (Sunday review)")
            return True

        # #128 T4: check_action_reminders now reads the clock via the injectable
        # telegram_commands._now_et() seam, and the conftest autouse fixture pins
        # _now_et_provider to a WEEKDAY by default — which would suppress reminder
        # 2 (Sunday review) and make this isolation test vacuous. Pin the seam to
        # the Sunday-5PM instant this test requires so reminder 2 fires and raises.
        # Still patch the module `datetime` so the inline
        # datetime.fromisoformat(created_at) parsing in reminders 3/5 keeps working.
        with patch("src.notifications.telegram_commands.connect_db", return_value=fake_conn), \
             patch("src.notifications.telegram.notify_action_required",
                   side_effect=fake_notify), \
             patch("src.notifications.telegram_commands._now_et_provider",
                   lambda: sunday_5pm), \
             patch("src.notifications.telegram_commands.datetime") as mock_dt:

            mock_dt.now.return_value = sunday_5pm
            mock_dt.fromisoformat = dt_mod.datetime.fromisoformat

            result = tc.check_action_reminders(db_path=":memory:")

        # sunday_review must not be in result (raised before sent.append)
        assert "sunday_review" not in result, (
            f"sunday_review must not appear — it raised before append; got {result!r}"
        )
        # At least one later reminder (api_rotation, score_training, or retrain_overdue)
        # must have fired, proving isolation — execution continued past reminder 2's failure.
        later_reminders = [r for r in result if r in ("api_rotation", "score_training",
                                                        "retrain_overdue")]
        assert len(later_reminders) > 0, (
            "Expected at least one of api_rotation/score_training/retrain_overdue to fire "
            f"after reminder 2 raised; got result={result!r}. "
            "This indicates function-wide except aborted all reminders after reminder 2."
        )


class TestSharedTelegramConfigSingleSource:
    """Regression-lock: _get_telegram_config lives in exactly one place."""

    def test_telegram_module_imports_config_from_shared(self):
        """Assert telegram.py's _get_telegram_config is the same object as _config's."""
        import src.notifications._config as cfg_mod
        import src.notifications.telegram as tg_mod

        assert tg_mod._get_telegram_config is cfg_mod._get_telegram_config, (
            "telegram.py must import _get_telegram_config from src.notifications._config, "
            "not define its own copy. Both function objects must be the same id()."
        )

    def test_telegram_commands_imports_config_from_shared(self):
        """Assert telegram_commands.py's _get_telegram_config is the same object as _config's."""
        import src.notifications._config as cfg_mod
        import src.notifications.telegram_commands as tc_mod

        assert tc_mod._get_telegram_config is cfg_mod._get_telegram_config, (
            "telegram_commands.py must import _get_telegram_config from src.notifications._config, "
            "not define its own copy. Both function objects must be the same id()."
        )
