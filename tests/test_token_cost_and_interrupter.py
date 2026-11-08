# -*- coding: utf-8 -*-
"""
Unit and Integration Tests for TokenCostTracker and TaskInterrupter
- Tests token counting and Gemini 3.8 Flash JPY pricing calculation
- Tests TaskInterrupter initialization and safe terminal teardown
"""

import unittest
import sys

# Add TUGUMIv6 root
sys.path.insert(0, "/data/data/com.termux/files/home/TUGUMIv6")

from interfaces.cli.token_cost_tracker import TokenCostTracker
from interfaces.cli.task_interrupter import TaskInterrupter
from rich.console import Console

class TestTokenCostTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = TokenCostTracker(usd_jpy_rate=155.0)

    def test_token_estimation(self):
        # English estimation: ~4 chars / token
        en_text = "Hello world this is a test string"
        self.assertGreater(self.tracker.estimate_tokens(en_text), 5)

        # Japanese estimation: ~1.2 chars / token
        ja_text = "こんにちは、拓磨様。つぐみです。"
        self.assertGreater(self.tracker.estimate_tokens(ja_text), 10)

    def test_pricing_calculation(self):
        # 10,000 prompt tokens, 5,000 completion tokens
        # Prompt cost: (10,000 / 1M) * $0.075 = $0.00075
        # Completion cost: (5,000 / 1M) * $0.300 = $0.00150
        # Total USD = $0.00225
        # Total JPY = 0.00225 * 155 = 0.34875 円
        meta = {
            "prompt_token_count": 10000,
            "candidates_token_count": 5000,
            "thoughts_token_count": 1000
        }
        res = self.tracker.record_turn(usage_metadata=meta)
        self.assertEqual(res["turn_prompt_tokens"], 10000)
        self.assertEqual(res["turn_completion_tokens"], 5000)
        self.assertAlmostEqual(res["turn_cost_usd"], 0.00225, places=5)
        self.assertAlmostEqual(res["turn_cost_jpy"], 0.34875, places=4)
        self.assertEqual(self.tracker.session_total, 15000)

    def test_render_cost_banner(self):
        # 1. ワイド画面（フル詳細表示：モデル名・詳細内訳が含まれる）
        console_wide = Console(record=True, width=120)
        self.tracker.record_turn(prompt_text="Hello", response_text="World")
        self.tracker.render_cost_banner(console_wide)
        output_wide = console_wide.export_text()
        self.assertIn("Gemini 3.8 Flash", output_wide)
        self.assertIn("¥", output_wide)

        # 2. スマホ・ナロー画面（スマート短縮表示：折返し防止）
        console_narrow = Console(record=True, width=60)
        self.tracker.render_cost_banner(console_narrow)
        output_narrow = console_narrow.export_text()
        self.assertIn("¥", output_narrow)
        self.assertIn("Turn:", output_narrow)

    def test_banner_and_status_dock_pinch_zoom_resilience(self):
        """画面をアップ（38カラム）にしたり引いたり（100カラム）してもロゴ・バナー・ドックが折り返し崩壊しないことを検証"""
        from interfaces.cli.cyber_theme import print_cyber_banner
        from interfaces.cli.status_dock import StatusDock
        from rich.cells import cell_len

        for width in (38, 50, 68, 100):
            for mode in ("light", "dark"):
                c = Console(record=True, width=width)
                print_cyber_banner(c, mode=mode, model_name="gemini-3.8-flash")
                dock = StatusDock(c)
                dock.render_dock(mode=mode, token_count=1250, cost_jpy=0.052, model_name="gemini-3.8-flash")
                lines = [line.rstrip() for line in c.export_text().splitlines() if line.strip()]
                # ソリッドブロックロゴの先頭行が欠損・折り返しなく1行に収まっていること
                self.assertTrue(any("▀▀█▀▀ █  █ █▀▀▀" in line for line in lines))
                # 全行が36セル以下（ドックも含め現在の画面幅以下）で折り返し崩壊ゼロであること
                for line in lines:
                    self.assertLessEqual(cell_len(line), width)


class TestTaskInterrupter(unittest.TestCase):
    def test_interrupter_lifecycle(self):
        console = Console()
        interrupter = TaskInterrupter(console)
        # Even if running in non-interactive CI/background, it should not crash
        with interrupter:
            pressed = interrupter.check_esc_pressed()
            self.assertIsInstance(pressed, bool)
        self.assertFalse(interrupter._is_active)

    def test_process_group_pause_and_resume(self):
        """サブプロセス実行中にSIGSTOPで一時停止し、SIGCONTで正常再開・完走できることを検証"""
        import subprocess
        import time
        proc = subprocess.Popen(
            "python3 -c 'import time; time.sleep(0.2); print(\"RESUMED_OK\")'",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True
        )
        TaskInterrupter.register_process(proc)
        try:
            TaskInterrupter.pause_all_active_processes()
            time.sleep(0.1)
            # 一時停止中はまだ終了していないこと
            self.assertIsNone(proc.poll())
            # 再開（SIGCONT）
            TaskInterrupter.resume_all_active_processes()
            stdout, stderr = proc.communicate(timeout=3.0)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("RESUMED_OK", stdout)
        finally:
            TaskInterrupter.unregister_process(proc)

    def test_process_group_termination_unblocks_child_pipes(self):
        """shell=True で孫プロセスがパイプを握っている場合でも terminate_all_active_processes で即座にアンブロックされることを検証"""
        import threading
        import time
        from tools.termux_tools import TermuxTools
        tt = TermuxTools()
        result_holder = {}

        def _runner():
            # 親シェルが別セッション(start_new_session=True)の孫デーモンを起動してパイプFDを保持し続ける最悪ケース
            result_holder["res"] = tt.run_termux_command(
                "python3 -c 'import subprocess, time; subprocess.Popen([\"sleep\", \"10\"], start_new_session=True); time.sleep(10)'",
                timeout=15.0
            )

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        time.sleep(0.25)
        start_kill = time.time()
        TaskInterrupter.terminate_all_active_processes()
        t.join(timeout=2.0)
        elapsed_kill = time.time() - start_kill
        self.assertFalse(t.is_alive(), "Child process pipe blocked run_termux_command() after termination!")
        self.assertLess(elapsed_kill, 0.25)
        self.assertEqual(result_holder["res"]["exit_code"], -15)

    def test_slash_commands_and_ruff_compatibility(self):
        """Ruff 0.17.4 検証互換性と CLI スラッシュコマンド群 (/ss, /donut, /sh vs /share 等) の回帰テスト"""
        import os
        from io import StringIO
        from unittest.mock import MagicMock, patch
        from rich.console import Console
        from core.verifier import SystemVerifier
        from interfaces.cli.commands.termux_commands import execute_shell_passthrough, handle_latest_screenshot_analysis
        from interfaces.cli.main import handle_donut_command

        # 1. SystemVerifier が Ruff 0.17.4 環境下で core/gemini_client.py を Exit Code 0 で通過すること
        verifier = SystemVerifier()
        tugumi_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res = verifier.verify_all_gates(os.path.join(tugumi_root, "core", "gemini_client.py"))
        self.assertTrue(res["passed"], f"SystemVerifier failed under Ruff 0.17.4: {res}")

        # 2. /sh vs /share のプレフィックス分離検証 (/share が /sh に誤認されないこと)
        buf_sh = StringIO()
        console_sh = Console(file=buf_sh, force_terminal=True)
        rc = execute_shell_passthrough("/sh echo SHELL_OK", console_sh, mode="light")
        self.assertEqual(rc, 0)
        self.assertIn("SHELL_OK", buf_sh.getvalue())

        # 3. /ss (handle_latest_screenshot_analysis) が EngineManager (engine.gemini.generate_content) 経由で正常推論できること
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        dummy_engine = MagicMock()
        del dummy_engine.generate_content
        del dummy_engine.client
        dummy_engine.gemini.generate_content.return_value = "VISION_ANALYSIS_SUCCESS"

        with patch("interfaces.cli.commands.termux_commands.get_latest_screenshot", return_value=__file__), \
             patch("os.path.getsize", return_value=2048), \
             patch("PIL.Image.open", return_value=MagicMock()):
            ok = handle_latest_screenshot_analysis("テスト解析", dummy_engine, console, mode="light")
            self.assertTrue(ok)
            self.assertIn("VISION_ANALYSIS_SUCCESS", buf.getvalue())
            self.assertNotIn("推論クライアントを取得できませんでした", buf.getvalue())

        # 4. /donut list と /donut config が未知コマンドエラーにならず正常動作すること
        buf_donut = StringIO()
        console_donut = Console(file=buf_donut, force_terminal=True)
        handle_donut_command("/donut list", console_donut, None, MagicMock(), MagicMock(), curr_mode="light")
        handle_donut_command("/donut config", console_donut, None, MagicMock(), MagicMock(), curr_mode="light")
        donut_out = buf_donut.getvalue()
        self.assertNotIn("未知のサブコマンド", donut_out)
        self.assertIn("Donut Browser Configuration", donut_out)

    def test_briefing_group_separation_and_html_renderer(self):
        """デイリーブリーフィングの乃木坂46/日向坂46完全分離規約およびHTMLレンダラー（太字・リンク・表）の検証"""
        import os
        from core.deep_research_engine import DeepResearchEngine

        tugumi_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(tugumi_root, "core", "briefing_engine.py"), encoding="utf-8") as f:
            b_src = f.read()

        # 1. 第2章（乃木坂46）と第3章（日向坂46）が独立した章として定義されていること
        self.assertIn("## 2. 💜 乃木坂46 専属ディープインテリジェンス", b_src)
        self.assertIn("## 3. 🩵 日向坂46 専属ディープインテリジェンス", b_src)
        self.assertIn("グループ混在・ちゃんぽん記述の完全禁止", b_src)

        # 2. DeepResearchEngine.render_beautiful_html が **太字**, [リンク](URL), |表| を正しくHTMLタグへ変換すること
        dre = DeepResearchEngine()
        sample_md = (
            "# テストタイトル\n\n"
            "- **井上和様**の最新記事は[公式ニュース](https://www.nogizaka46.com)を参照\n\n"
            "| 項目 | 値 |\n"
            "| :--- | :--- |\n"
            "| **天気** | 快晴 ☀️ |\n"
        )
        html_out = dre.render_beautiful_html("テスト", sample_md, category="デイリーブリーフィング")
        self.assertNotIn("**井上和様**", html_out)
        self.assertIn("<strong", html_out)
        self.assertIn('href="https://www.nogizaka46.com"', html_out)
        self.assertIn("<table", html_out)
        self.assertIn("<th", html_out)


if __name__ == "__main__":
    unittest.main()
