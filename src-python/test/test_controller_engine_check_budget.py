"""起動時のエンジンの確認は、全体の時間の上限で打ち切る。

個々の要求の時間の上限は SDK ごとに違い、少しずつ応答を返し続けるサーバーでは効かない。
確認が終わらないと起動画面のまま進まなかった。
"""

import threading
import time
import unittest
from unittest.mock import patch

import controller


class EngineCheckBudgetTests(unittest.TestCase):
    def test_slow_engines_are_left_out_and_startup_goes_on(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)

        def check(engine):
            if engine == "Stalled":
                release.wait(5)
            return engine, True, False, None, None

        started = time.monotonic()
        with patch.object(controller, "_ENGINE_CHECK_BUDGET_SEC", 0.2), patch.object(controller, "printLog"):
            results = controller._runEngineChecks(check, ["Fast", "Stalled"], "Test")

        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(results, {"Fast": (True, False, None, None)})

    def test_all_results_are_returned_when_checks_finish(self) -> None:
        results = controller._runEngineChecks(lambda e: (e, e == "A", False, [e], e), ["A", "B"], "Test")

        self.assertEqual(results, {"A": (True, False, ["A"], "A"), "B": (False, False, ["B"], "B")})


if __name__ == "__main__":
    unittest.main()
