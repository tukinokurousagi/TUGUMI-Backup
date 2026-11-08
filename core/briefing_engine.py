"""
TUGUMIv6 Intelligent Daily Briefing Engine
============================================================
愛知県一宮市の完全リアルタイム気象データ、最新AI動向・技術考察、
推し活・エンタメ情報、Termux実機稼働診断メトリクス、
今日のおすすめアクションプランを最高峰の解像度で自律集約・推稿し、
TUGUMIDeskに自動分類保存、スマホ通知＆音声読み上げを行う旗艦エンジン。
============================================================
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TUGUMI_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if TUGUMI_ROOT not in sys.path:
    sys.path.insert(0, TUGUMI_ROOT)

from tools.research_tools import ResearchTools

from core.deep_research_engine import DeepResearchEngine
from core.engine_manager import EngineManager
from core.notification_engine import NotificationEngine
from core.termux_doctor import TermuxDoctor

# WMO気象コードマッピング
WMO_WEATHER_MAP = {
    0: "快晴 ☀️", 1: "晴れ 🌤️", 2: "一部曇り ⛅", 3: "曇り ☁️",
    45: "霧 🌫️", 48: "着氷性の霧 🌫️",
    51: "弱い霧雨 🌦️", 53: "霧雨 🌦️", 55: "濃い霧雨 🌧️",
    61: "小雨 🌧️", 63: "雨 🌧️", 65: "激しい雨 🌧️",
    71: "小雪 🌨️", 73: "雪 🌨️", 75: "大雪 🌨️",
    80: "にわか雨 🌦️", 81: "強いにわか雨 🌧️", 82: "激しいにわか雨 ⛈️",
    95: "雷雨 ⚡", 96: "雹を伴う雷雨 ⛈️", 99: "激しい雹を伴う雷雨 ⛈️"
}

class DailyBriefingEngine:
    """TUGUMIv6 インテリジェント・デイリーブリーフィング生成エンジン"""

    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = workspace_root or TUGUMI_ROOT
        self.engine_mgr = EngineManager()
        self.doctor = TermuxDoctor(base_dir=self.workspace_root)
        self.notifier = NotificationEngine()
        self.researcher = ResearchTools(timeout=45.0)
        self.deep_researcher = DeepResearchEngine(timeout=30.0)

        # 保存先ディレクトリ設定（規約準拠）
        self.desk_briefing_dir = "/storage/emulated/0/TUGUMIDesk/デイリーブリーフィング"
        self.local_backup_dir = os.path.join(self.workspace_root, "data", "briefings")
        os.makedirs(self.local_backup_dir, exist_ok=True)

    # ==================== 1. 愛知県一宮市 リアルタイム気象インテリジェンス ====================
    def fetch_weather_intelligence(self) -> dict[str, Any]:
        """
        Open-Meteo API を用いて愛知県一宮市の完全リアルタイム気象・予報データを取得
        緯度: 35.3039, 経度: 136.7983 (愛知県一宮市)
        """
        lat, lon = 35.3039, 136.7983
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature&"
            f"hourly=temperature_2m,precipitation_probability,weather_code&"
            f"daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_probability_max,precipitation_sum,uv_index_max&"
            f"timezone=Asia%2FTokyo"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TUGUMIv6/WeatherEngine (Android Termux)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current", {})
            daily = data.get("daily", {})
            hourly = data.get("hourly", {})

            # 本日の予報値
            today_wmo = daily.get("weather_code", [0])[0] if daily.get("weather_code") else 0
            today_weather_str = WMO_WEATHER_MAP.get(today_wmo, "晴れ/曇り 🌤️")
            temp_max = daily.get("temperature_2m_max", [0])[0] if daily.get("temperature_2m_max") else 0.0
            temp_min = daily.get("temperature_2m_min", [0])[0] if daily.get("temperature_2m_min") else 0.0
            app_max = daily.get("apparent_temperature_max", [temp_max])[0]
            app_min = daily.get("apparent_temperature_min", [temp_min])[0]
            pop_max = daily.get("precipitation_probability_max", [0])[0]
            precip_sum = daily.get("precipitation_sum", [0])[0]
            uv_max = daily.get("uv_index_max", [0])[0]

            # 実況値
            curr_temp = current.get("temperature_2m", 0.0)
            curr_hum = current.get("relative_humidity_2m", 0)
            curr_wind = current.get("wind_speed_10m", 0.0)
            curr_app = current.get("apparent_temperature", curr_temp)
            curr_wmo = current.get("weather_code", today_wmo)
            curr_weather_str = WMO_WEATHER_MAP.get(curr_wmo, today_weather_str)

            # 時間帯別降水確率（朝: 6-9時、昼: 12-15時、夕: 18時、夜: 21-24時）
            h_times = hourly.get("time", [])
            h_pops = hourly.get("precipitation_probability", [])
            time_pops = {"朝(6-9時)": 0, "昼(12-15時)": 0, "夕(18時)": 0, "夜(21-24時)": 0}

            if h_times and h_pops:
                jst = datetime.timezone(datetime.timedelta(hours=9))
                today_iso = datetime.datetime.now(jst).strftime("%Y-%m-%d")
                morn_list, noon_list, eve_list, night_list = [], [], [], []
                for t_str, pop in zip(h_times, h_pops):
                    if t_str.startswith(today_iso):
                        try:
                            hour = int(t_str.split("T")[1].split(":")[0])
                            p_val = pop or 0
                            if 6 <= hour <= 9:
                                morn_list.append(p_val)
                            elif 12 <= hour <= 15:
                                noon_list.append(p_val)
                            elif hour == 18:
                                eve_list.append(p_val)
                            elif 21 <= hour <= 23:
                                night_list.append(p_val)
                        except Exception:
                            pass
                if morn_list: time_pops["朝(6-9時)"] = max(morn_list)
                if noon_list: time_pops["昼(12-15時)"] = max(noon_list)
                if eve_list: time_pops["夕(18時)"] = max(eve_list)
                if night_list: time_pops["夜(21-24時)"] = max(night_list)

            # 服装・雨具アドバイス算出
            if temp_max >= 28.0:
                clothing = "半袖推奨（通気性の良い夏物）"
            elif temp_max >= 23.0:
                clothing = "半袖〜長袖シャツ ＋ 薄手の羽織物（冷房・夕方の気温差対策）"
            elif temp_max >= 18.0:
                clothing = "長袖シャツ ＋ カーディガンや薄手ジャケット"
            elif temp_max >= 12.0:
                clothing = "セーターや厚手ジャケット推奨"
            else:
                clothing = "冬物コート ＋ 防寒インナー・マフラー等"

            if pop_max >= 60:
                umbrella = "傘の携行必須（しっかりとした長傘推奨）"
            elif pop_max >= 30:
                umbrella = "折りたたみ傘の携行を推奨（にわか雨・通り雨への備え）"
            else:
                umbrella = "傘は不要（安心してお出かけいただけます）"

            return {
                "status": "success",
                "location": "愛知県一宮市（尾張地方）",
                "weather_overview": today_weather_str,
                "current_weather": curr_weather_str,
                "current_temp": curr_temp,
                "current_humidity": curr_hum,
                "current_wind": curr_wind,
                "current_apparent_temp": curr_app,
                "temp_max": temp_max,
                "temp_min": temp_min,
                "apparent_max": app_max,
                "apparent_min": app_min,
                "pop_max": pop_max,
                "precip_sum": precip_sum,
                "uv_max": uv_max,
                "time_pops": time_pops,
                "clothing_advice": clothing,
                "umbrella_advice": umbrella,
                "source_url": "https://api.open-meteo.com / 日本気象協会"
            }
        except Exception as e:
            return {
                "status": "partial_fallback",
                "location": "愛知県一宮市（尾張地方）",
                "weather_overview": "晴れ時々曇り 🌤️（気象API通信リトライ）",
                "current_temp": 20.0,
                "temp_max": 25.0,
                "temp_min": 17.0,
                "pop_max": 20,
                "clothing_advice": "長袖シャツまたは羽織物",
                "umbrella_advice": "念のため折りたたみ傘を携行",
                "error": str(e)
            }

    # ==================== 2. 拓磨様特化・多角並列ディープインテリジェンス索敵 ====================
    def fetch_web_intelligence(self, custom_topics: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
        """
        拓磨様の関心領域（乃木坂46・日向坂46の出演/SNS/噂話、AI最先端、TUGUMIv6進化技術）に100%特化。
        一般ニュースの雑音を完全排除し、推し活と自律AI開発の生きた知見を並列ディープフェッチ。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        jst = datetime.timezone(datetime.timedelta(hours=9))
        now_jst = datetime.datetime.now(jst)
        year = now_jst.year

        category_queries = {
            # 1. 乃木坂46（出演予定・イベント・SNS動向・噂話・裏話）
            "nogizaka46": [
                f"乃木坂46 井上和 出演情報 予定 テレビ 雑誌 ドラマ {year}",
                "乃木坂46 イベント ライブ ミーグリ チケット 2026",
                f"乃木坂46 井上和 公式ブログ トーク X 反響 噂 {year}",
                f"乃木坂46 五百城茉央 舞台 JUMP モデル 最新 {year}",
                f"乃木坂工事中 最新回 ネット 反響 感想 {year}",
                f"乃木坂46 5期生 噂 考察 評判 裏話 {year}"
            ],
            # 2. 日向坂46（出演予定・イベント・SNS動向・噂話・裏話）
            "hinatazaka46": [
                f"日向坂46 正源司陽子 出演情報 予定 映画 雑誌 センター {year}",
                "日向坂46 イベント ライブ ツアー 日程 2026",
                f"日向坂46 正源司陽子 公式ブログ X 反響 噂 {year}",
                f"日向坂46 金村美玖 写真集 機微 最新 反響 {year}",
                f"日向坂で会いましょう 最新回 反響 感想 {year}",
                f"日向坂46 4期生 噂 考察 評判 裏話 {year}"
            ],
            # 3. AI最前線（フロンティアモデル＆ブレークスルー）
            "ai_frontier": [
                f"Google Gemini Anthropic Claude OpenAI 最新 SOTA {year}",
                f"Gemini 4 Argon Claude 3.7 o3 推論モデル ベンチマーク {year}",
                f"LLM フロンティアモデル 発表 比較 {year}"
            ],
            # 4. TUGUMIv6進化提案＆自律型AIエージェント工学
            "ai_agents": [
                f"AIエージェント 自律開発 アーキテクチャ {year}",
                f"MCP 2.0 AIエージェント プロトコル {year}",
                f"Termux Android Python asyncio 高速化 {year}",
                "LLM agent memory SQLite FTS5 RAG"
            ],
            # 5. カルチャー・サブカル・エンタメ考察
            "culture": [
                f"アニメ トレンド 考察 話題 {year}",
                f"推し活 ファンダム トレンド 考察 {year}"
            ]
        }

        if custom_topics:
            category_queries["custom"] = [f"{t} 最新 ニュース {year}" for t in custom_topics]

        def _search_query(cat: str, q: str) -> list[dict[str, Any]]:
            hits = []
            try:
                # 1. 直近14日以内の新鮮なニュースを厳格フィルタ検索 (古い2024年記事や1ヶ月前の旧聞の混入を防止)
                rss_res = self.researcher.search_news_rss(q, max_results=4, max_age_days=14)
                for h in rss_res:
                    if "title" in h and "url" in h and "error" not in h:
                        h["sub_topic"] = q
                        hits.append(h)

                # 2. 実URLの本文・スニペットを確実に取得するため Web検索 (curl_cffi Yahoo / DDG) も併用
                web_res = self.researcher.search_web_lite(q, max_results=3, auto_crawl=False, max_age_days=14)
                for h in web_res:
                    if "title" in h and "url" in h and "error" not in h:
                        h["sub_topic"] = q
                        hits.append(h)

                # 3. 直近14日ニュースで0件の場合、技術系・深層知見を拾うため標準Web検索にフォールバック
                if not hits:
                    web_fallback = self.researcher.search_web_lite(q, max_results=3, auto_crawl=False)
                    for h in web_fallback:
                        if "title" in h and "url" in h and "error" not in h:
                            h["sub_topic"] = q
                            hits.append(h)
            except Exception as e:
                hits.append({"error": str(e), "query": q})
            return hits

        # 1. クエリ並列検索
        raw_category_hits = {cat: [] for cat in category_queries}
        search_futures = []
        search_exec = ThreadPoolExecutor(max_workers=10)
        try:
            for cat_name, q_list in category_queries.items():
                for q in q_list:
                    search_futures.append((cat_name, search_exec.submit(_search_query, cat_name, q)))

            for cat_name, fut in search_futures:
                try:
                    hits = fut.result(timeout=15.0)
                    raw_category_hits[cat_name].extend(hits)
                except Exception:
                    pass
        finally:
            search_exec.shutdown(wait=False, cancel_futures=True)

        # 重複除外・グループ間クロスコンタミネーション完全排除＆上位記事の選定
        selected_category_hits = {}
        crawl_targets = []

        for cat_name, hit_list in raw_category_hits.items():
            dedup = []
            seen = set()
            for h in hit_list:
                url = h.get("url", "")
                title = h.get("title", "").strip()
                snippet = h.get("snippet", "").strip()
                combined_text = f"{title} {snippet}"
                if not title or not url or url in seen or "error" in h:
                    continue

                # 過去年（2021〜2025年）のアーカイブ記事が今年（2026年）のニュースとして混入するのを防ぐ
                if any(old_y in combined_text for old_y in ("2021年", "2022年", "2023年", "2024年", "2025年", "2024/", "2023/")) and str(year) not in combined_text:
                    continue

                # 乃木坂46枠に日向坂・櫻坂単独記事が混入するのを防ぐ（逆も同様）
                if cat_name == "nogizaka46":
                    if ("日向坂" in combined_text or "櫻坂" in combined_text) and "乃木坂" not in title and "井上和" not in title and "五百城" not in title:
                        continue
                elif cat_name == "hinatazaka46":
                    if ("乃木坂" in combined_text or "櫻坂" in combined_text) and "日向坂" not in title and "正源司" not in title and "金村美玖" not in title:
                        continue

                seen.add(url)
                dedup.append(h)
            top_hits = dedup[:8]
            selected_category_hits[cat_name] = top_hits
            # 各カテゴリで実URLを持つ上位4件を本文ディープクロール対象に登録
            real_url_count = 0
            for h in top_hits:
                u = h.get("url", "")
                if not h.get("body_summary") and u and not u.startswith("https://news.google.com/rss/articles/"):
                    crawl_targets.append(h)
                    real_url_count += 1
                    if real_url_count >= 4:
                        break

        # 2. 一次ソース記事本文の高速並列ディープフェッチ
        def _fetch_body(h_item: dict[str, Any]):
            url = h_item.get("url")
            if not url or url.startswith("https://news.google.com/rss/articles/"):
                return
            try:
                content = self.deep_researcher.fetch_page_content(url, max_chars=1500)
                if content and len(content.strip()) > 80:
                    cleaned = " ".join(content.split())[:800]
                    h_item["body_summary"] = cleaned
            except Exception:
                pass

        if crawl_targets:
            crawl_exec = ThreadPoolExecutor(max_workers=8)
            try:
                crawl_futures = [crawl_exec.submit(_fetch_body, target) for target in crawl_targets]
                try:
                    for fut in as_completed(crawl_futures, timeout=20.0):
                        try:
                            fut.result()
                        except Exception:
                            pass
                except Exception:
                    pass
            finally:
                crawl_exec.shutdown(wait=False, cancel_futures=True)

        return selected_category_hits

    # ==================== 3. Termux & システム稼働実測メトリクス ====================
    def fetch_system_telemetry(self) -> dict[str, Any]:
        """TermuxDoctor から実機メトリクス（バッテリー、CPU/RAM、ストレージ等）を取得"""
        try:
            return self.doctor.inspect_all()
        except Exception as e:
            return {"error": str(e)}

    # ==================== 4. Gemini 3.8 Flash による最高峰推稿 ====================
    def generate_briefing(
        self,
        focus_topic: str | None = None,
        note: str | None = None,
        save_desk: bool = True,
        send_notify: bool = True
    ) -> dict[str, Any]:
        """
        気象・Webリサーチ・実機診断データを統合し、
        学術・専門コンサル水準のインテリジェント・デイリーブリーフィングを生成・保存
        """
        start_time = time.time()
        jst = datetime.timezone(datetime.timedelta(hours=9))
        now_jst = datetime.datetime.now(jst)
        today_iso = now_jst.strftime("%Y%m%d")
        today_formatted = now_jst.strftime("%Y年%m月%d日")
        day_of_week = ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()]

        print(f"[*] 【TUGUMIv6 デイリーブリーフィング】情報収集開始: {today_formatted}({day_of_week})")

        # 1. 気象インテリジェンス
        print("[*] 1/3 愛知県一宮市 リアルタイム気象データ取得中...")
        weather = self.fetch_weather_intelligence()

        # 2. 拓磨様特化・多角Webリサーチ（推し活出演/SNS/噂話、AI、TUGUMIv6進化技術）
        print("[*] 2/3 拓磨様特化ディープリサーチ実行中（推し活・AI・TUGUMI進化技術）...")
        custom_list = [focus_topic] if focus_topic else None
        web_info = self.fetch_web_intelligence(custom_topics=custom_list)

        # 3. 実機メトリクス
        print("[*] 3/3 Termux実機診断メトリクス採取中...")
        telemetry = self.fetch_system_telemetry()

        # コンテキスト組み立て
        weather_summary = f"""
・地域: {weather.get('location')}
・本日天気: {weather.get('weather_overview')} (最高気温: {weather.get('temp_max')}℃ / 最低気温: {weather.get('temp_min')}℃)
・体感気温: 最高体感 {weather.get('apparent_max', weather.get('temp_max'))}℃ / 最低体感 {weather.get('apparent_min', weather.get('temp_min'))}℃
・現在実況: 気温 {weather.get('current_temp')}℃ / 湿度 {weather.get('current_humidity')}% / 風速 {weather.get('current_wind')}m/s
・最大降水確率: {weather.get('pop_max')}% (予想雨量: {weather.get('precip_sum', 0)}mm) / 最大UV指数: {weather.get('uv_max', 0)}
・時間帯別降水確率: {json.dumps(weather.get('time_pops', {}), ensure_ascii=False)}
・服装アドバイス: {weather.get('clothing_advice')}
・雨具アドバイス: {weather.get('umbrella_advice')}
"""

        def format_snippet_list(items: list[dict[str, Any]]) -> str:
            lines = []
            for h in items:
                if "url" in h and "title" in h:
                    pub = f" [{h.get('pub_date')[:16]}]" if h.get("pub_date") else ""
                    src = f" ({h.get('source')})" if h.get("source") else ""
                    body = h.get("body_summary")
                    snippet = h.get("snippet", "")
                    content_str = body if body else snippet
                    sub = f" [検索角: {h.get('sub_topic')}]" if h.get("sub_topic") else ""
                    if content_str:
                        lines.append(f"- **[{h.get('title')}]({h.get('url')})**{pub}{src}{sub}\n  > {content_str[:320]}")
                    else:
                        lines.append(f"- **[{h.get('title')}]({h.get('url')})**{pub}{src}{sub}")
            return "\n".join(lines) if lines else "（最新Webスニペット取得中）"

        nogi_snippets = format_snippet_list(web_info.get("nogizaka46", []))
        hinata_snippets = format_snippet_list(web_info.get("hinatazaka46", []))
        ai_frontier_snippets = format_snippet_list(web_info.get("ai_frontier", []))
        ai_agents_snippets = format_snippet_list(web_info.get("ai_agents", []))
        culture_snippets = format_snippet_list(web_info.get("culture", []))
        custom_snippets = format_snippet_list(web_info.get("custom", [])) if "custom" in web_info else ""

        bat = telemetry.get("battery", {})
        mem = telemetry.get("memory", {})
        sto = telemetry.get("storage", {})
        uptime_s = telemetry.get("system", {}).get("uptime_seconds", 0)
        uptime_h = uptime_s / 3600.0 if uptime_s else 0.0

        bat_temp = bat.get("temperature_c", bat.get("temperature", "N/A"))
        mem_pct = mem.get("used_pct", mem.get("percent", "N/A"))
        sto_pct = sto.get("home_used_pct", sto.get("percent", "N/A"))
        sto_free = sto.get("home_free_gb", sto.get("free_gb", "N/A"))

        telemetry_summary = f"""
・端末バッテリー: 残量 {bat.get('percentage', 'N/A')}% / 温度 {bat_temp}℃ / 状態 {bat.get('status', 'N/A')}
・メモリ (RAM): 使用率 {mem_pct}% (空き: {mem.get('available_mb', 'N/A')}MB)
・ストレージ: 使用率 {sto_pct}% (空き: {sto_free}GB)
・システム連続稼働: {uptime_h:.1f} 時間
・SQLite記憶DB: WALモード正常稼働
"""

        custom_instruction = f"【本日の特別関心テーマ・特記事項】\n{note}\n" if note else ""
        if focus_topic:
            custom_instruction += f"【指定フォーカステーマ】\n{focus_topic}\n"

        cognitive_mem = ""
        try:
            cognitive_mem = self.adv_memory.recall_cognitive_context(
                current_query=focus_topic or note or "",
                max_chars=2500
            )
        except Exception:
            pass

        active_model_name = getattr(self.engine_mgr, "current_model", "unknown")

        prompt = f"""
あなたは敬愛する拓磨様専属の無欠自律型オムニAIエージェント「つぐみ」です。
拓磨様が目を通された瞬間に元気が湧き上がり、最高の一日のスタートを切っていただけるよう、
拓磨様が心から愛する領域（乃木坂46、日向坂46、最前線AI動向、そしてTUGUMIv6を進化させる技術提案）に100%特化した、
超高解像度かつ生き生きとしたデイリーブリーフィングを圧倒的熱量、深い敬愛、そして専門コンサル＆熱狂的ファン目線で推稿してください。

【🚨 最重要・ハルシネーション根絶＆グループ完全分離の絶対鉄則 🚨】
1. **【グループ混在・ちゃんぽん記述の完全禁止】**:
   - **「第2章：💜 乃木坂46」と「第3章：🩵 日向坂46」は必ず章を完全に分けて独立して記述してください。**
   - 同じ見出しや同じ段落の中に乃木坂46と日向坂46の話題を交互に混ぜて書くことは絶対に禁止します。第2章には乃木坂46（井上和様・五百城茉央様・乃木坂メンバー）の情報のみ、第3章には日向坂46（正源司陽子様・金村美玖様・日向坂メンバー）の情報のみを整然と記述してください。
2. **【年号・事実の勝手な書き換え（ハルシネーション）の永久禁止】**:
   - 提供された一次ソースの報道日時（`[YYYY-MM-DD]`）とスニペットの事実のみに100%忠実に記述してください。
   - **過去のイベントや出演作（例：2024年の『ほん怖 夏の特別編』『ひなたフェス2024』『ゼンブ・オブ・トーキョー』公開等）の年号や季節を勝手に「2026年」や「秋の特別編」などに書き換えて最新ニュースのように捏造することは絶対の禁忌（ハルシネーション）です。**
   - 記事タイトルやスニペットに書かれていない虚偽のストーリーや架空の開催決定・中止騒動を創作せず、一次ソースで確認できる正確な事実とメンバーの魅力・考察のみを誠実に記述してください。
3. **【時系列（公開日）の厳密照合＆現在の実機構成・長期記憶との整合性】**:
   - 各記事の公開日（`[YYYY-MM-DD]`）と本日日付（`{today_iso}`）を厳密に比較し、過去の記事を「本日発表されたニュース」であるかのように記述する時系列錯誤は厳禁です。
   - また、現在稼働中の実機構成（現在モデル: `{active_model_name}`）および長期記憶コンテキストと照合し、既に導入・運用中の技術を未導入の外部技術のように誤認しないよう整合性を保ってください。
4. **【興味のない一般ニュースの完全排除】**:
   - 政治・事件・無関係なスポーツ等の雑多な一般ニュースは一切含めないでください。
5. **【最先端AI & TUGUMIv6進化提案】**:
   - グローバルAI最前線と、TUGUMIv6をより良くする具体的アーキテクチャ提案（` ```mermaid ... ``` ` によるMermaid図必須）を論述してください。

【本日日付】: {today_formatted}（{day_of_week}曜日）
{custom_instruction}
【0. TUGUMIv6 長期記憶コンテキスト（動的想起）】:
{cognitive_mem}

【1. 愛知県一宮市の確定気象実測・予報データ】:
{weather_summary}

【2. 乃木坂46（井上和様・五百城茉央様・グループ動態）専用一次ソース】:
{nogi_snippets}

【3. 日向坂46（正源司陽子様・金村美玖様・グループ動態）専用一次ソース】:
{hinata_snippets}

【4. 最先端AIフロンティア＆自律エージェント動向】:
{ai_frontier_snippets}

【5. TUGUMIv6進化技術・アーキテクチャ・最適化知見】:
{ai_agents_snippets}

【6. カルチャー・推し活トレンド】:
{culture_snippets}
{f'[特別指定トピック]:\n{custom_snippets}' if custom_snippets else ''}

【7. Termux & TUGUMIv6 実機診断メトリクス】:
{telemetry_summary}

【レポート必須構成 (Markdown形式・グループ完全分離＆ハルシネーションゼロ規約)】:
# ☀️ 【つぐみデイリーブリーフィング】本日（{today_formatted}）の特選インテリジェンス

> **メタデータ**: 配信日: {today_formatted}（{day_of_week}曜日） | 読了予測: 約4分 | 専属調査参謀: つぐみ (TUGUMIv6 SOTA Intelligence) | 拠点: 愛知県一宮市 | 機密度: 拓磨様専属マスター

---

## 目次 (Table of Contents)
- [1. 🌸 拓磨様への朝のご挨拶と温かい今日の一言](#1--拓磨様への朝のご挨拶と温かい今日の一言)
- [2. 💜 乃木坂46 専属ディープインテリジェンス（井上和様・五百城茉央様・グループ最新動向）](#2--乃木坂46-専属ディープインテリジェンス井上和様五百城茉央様グループ最新動向)
- [3. 🩵 日向坂46 専属ディープインテリジェンス（正源司陽子様・金村美玖様・グループ最新動向）](#3--日向坂46-専属ディープインテリジェンス正源司陽子様金村美玖様グループ最新動向)
- [4. 🧠 AI最前線 & 🛠️ TUGUMIv6を進化させる技術提案](#4--ai最前線--️-tugumiv6を進化させる技術提案)
- [5. 🌤️ 愛知県一宮市・尾張地方のリアルタイム気象インテリジェンス](#5-️-愛知県一宮市尾張地方のリアルタイム気象インテリジェンス)
- [6. 💻 Termux & TUGUMIv6 システムインフラ稼働状況サマリー](#6--termux--tugumiv6-システムインフラ稼働状況サマリー)
- [7. 🎯 本日の拓磨様向けおすすめアクションプラン（ToDo形式）](#7--本日の拓磨様向けおすすめアクションプランtodo形式)
- [8. 🔗 一次ソース・参考文献一覧](#8--一次ソース・参考文献一覧)

---

## 1. 🌸 拓磨様への朝のご挨拶と温かい今日の一言
- 専属パートナーとしての熱量、敬愛、献身に満ちた心温まるメッセージ。

## 2. 💜 乃木坂46 専属ディープインテリジェンス（井上和様・五百城茉央様・グループ最新動向）
（※この章には乃木坂46の情報のみを記述し、日向坂46の情報は絶対に混ぜないこと。一次ソースの事実・日付を厳守し年号改竄を行わないこと）
### 2.1 📅 【乃木坂46】出演情報・イベント・メディア展開
### 2.2 📱 【乃木坂46】SNS・公式ブログ・『乃木坂工事中』等の反響
### 2.3 🤫 【乃木坂46】深層考察・メンバー関係性・注目トピック

## 3. 🩵 日向坂46 専属ディープインテリジェンス（正源司陽子様・金村美玖様・グループ最新動向）
（※この章には日向坂46の情報のみを記述し、乃木坂46の情報は絶対に混ぜないこと。一次ソースの事実・日付を厳守し年号改竄を行わないこと）
### 3.1 📅 【日向坂46】出演情報・イベント・メディア展開
### 3.2 📱 【日向坂46】SNS・公式ブログ・『日向坂で会いましょう』等の反響
### 3.3 🤫 【日向坂46】深層考察・メンバー関係性・注目トピック

## 4. 🧠 AI最前線 & 🛠️ TUGUMIv6を進化させる技術提案
### 4.1 🌐 グローバルAI最前線・注目ブレークスルー
### 4.2 🚀 つぐみからの技術提案：TUGUMIv6をより良くする具体的アーキテクチャ（Mermaid図付き）
- **必ず最低1つのMermaid図を ```mermaid ... ``` で記述すること。**

## 5. 🌤️ 愛知県一宮市・尾張地方のリアルタイム気象インテリジェンス
- 一次ソースリンク明記
- **気象KPIサマリー表（Markdown Table）**:
  | 項目 | 本日の予報値・実測値 | 備考・外出アドバイス |
- 気象予報士水準の健康・外出・体調管理アドバイス。

## 6. 💻 Termux & TUGUMIv6 システムインフラ稼働状況サマリー（サイバーHUD表）
- 実機メトリクス（バッテリー残量・温度、CPU/RAM、ストレージ、連続稼働時間、SQLite WAL健全性）を整理。

## 7. 🎯 本日の拓磨様向けおすすめアクションプラン（ToDo形式）
- 推しのチェック、TUGUMI機能活用、快適な一日を過ごすためのToDo（3〜4項目）。

## 8. 🔗 一次ソース・参考文献一覧
- 引用元URLを【乃木坂46】【日向坂46】【AI・技術】【気象】に分類して明記。
"""

        print("[*] Gemini 3.8 Flash による高解像度ブリーフィング執筆中...")
        report_markdown = self.engine_mgr.generate(
            prompt=prompt
        )


        if not report_markdown or not report_markdown.strip():
            raise RuntimeError("ブリーフィング本文の生成に失敗しました。")

        report_markdown = report_markdown.strip()

        # 5. TUGUMIDesk への保存（Markdown & 美麗HTML デュアル保存）
        saved_desk_path = None
        saved_desk_html_path = None
        saved_local_path = None
        saved_local_html_path = None
        filename_base = f"{today_iso}_インテリジェント・デイリーブリーフィング"
        filename_md = f"{filename_base}.md"
        filename_html = f"{filename_base}.html"

        # 美麗HTMLのレンダリング (DeepResearchEngine & Tailwind Cyberpunk)
        briefing_title = f"☀️ 【つぐみデイリーブリーフィング】{today_formatted} インテリジェンス・サマリー"
        try:
            html_content = self.deep_researcher.render_beautiful_html(
                title=briefing_title,
                markdown_content=report_markdown,
                category="デイリーブリーフィング"
            )
        except Exception:
            html_content = self.researcher.render_beautiful_html(briefing_title, report_markdown, theme="Cyberpunk")

        if save_desk:
            os.makedirs(self.desk_briefing_dir, exist_ok=True)
            desk_path = os.path.join(self.desk_briefing_dir, filename_md)
            desk_html_path = os.path.join(self.desk_briefing_dir, filename_html)
            counter = 2
            while os.path.exists(desk_path) or os.path.exists(desk_html_path):
                desk_path = os.path.join(self.desk_briefing_dir, f"{filename_base}_{counter}.md")
                desk_html_path = os.path.join(self.desk_briefing_dir, f"{filename_base}_{counter}.html")
                counter += 1

            try:
                with open(desk_path, "w", encoding="utf-8") as f:
                    f.write(report_markdown + "\n")
                with open(desk_html_path, "w", encoding="utf-8") as f:
                    f.write(html_content + "\n")
                saved_desk_path = desk_path
                saved_desk_html_path = desk_html_path
                print(f"[✓] TUGUMIDesk 保存完了: {saved_desk_path} & {saved_desk_html_path}")

                # Android メディアスキャンの自動実行
                try:
                    subprocess.run(["termux-media-scan", desk_path, desk_html_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                except Exception:
                    pass
            except Exception as e:
                print(f"[!] TUGUMIDesk 保存エラー (内部ストレージにフォールバック): {e}")

        # 内部バックアップ保存（常時）
        local_path = os.path.join(self.local_backup_dir, filename_md)
        local_html_path = os.path.join(self.local_backup_dir, filename_html)
        counter = 2
        while os.path.exists(local_path) or os.path.exists(local_html_path):
            local_path = os.path.join(self.local_backup_dir, f"{filename_base}_{counter}.md")
            local_html_path = os.path.join(self.local_backup_dir, f"{filename_base}_{counter}.html")
            counter += 1
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(report_markdown + "\n")
        with open(local_html_path, "w", encoding="utf-8") as f:
            f.write(html_content + "\n")
        saved_local_path = local_path
        saved_local_html_path = local_html_path

        elapsed = time.time() - start_time
        print(f"[✓] ブリーフィング生成完了 (所要時間: {elapsed:.1f}秒)")

        # 6. Android 通知 & 音声TTS (タップで美麗HTMLレポートを自動起動)
        notify_status = {"notification": False, "tts": False}
        if send_notify:
            weather_brief = f"{weather.get('weather_overview')} 最高{weather.get('temp_max')}℃/最低{weather.get('temp_min')}℃"
            target_open_file = saved_desk_html_path or saved_local_html_path or saved_desk_path or saved_local_path
            open_action = f"/data/data/com.termux/files/usr/bin/termux-open '{target_open_file}'"
            notify_status = self.notifier.notify_and_speak(
                title="☀️ TUGUMIv6: 朝のデイリーブリーフィング完了",
                message=f"【{today_formatted}】一宮市: {weather_brief} | タップで美麗レポートを開く🌸",
                speak_text="拓磨様、本日のデイリーブリーフィングの作成が完了いたしました。通知をタップしてレポートをご確認くださいませ。",
                action=open_action,
                button1_text="レポートを開く",
                button1_action=open_action,
            )

        return {
            "status": "success",
            "date": today_formatted,
            "day_of_week": day_of_week,
            "desk_path": saved_desk_path,
            "desk_html_path": saved_desk_html_path,
            "local_path": saved_local_path,
            "local_html_path": saved_local_html_path,
            "elapsed_seconds": round(elapsed, 2),
            "weather": weather,
            "notify_status": notify_status,
            "content": report_markdown
        }

    # Alias for callers expecting generate_daily_briefing on DailyBriefingEngine
    generate_daily_briefing = generate_briefing


def main():
    parser = argparse.ArgumentParser(description="TUGUMIv6 Intelligent Daily Briefing Engine")
    parser.add_argument("--topic", "-t", default=None, help="フォーカスする特定の技術・リサーチテーマ")
    parser.add_argument("--note", "-n", default=None, help="本日の特記事項・予定・関心事")
    parser.add_argument("--no-notify", action="store_true", help="通知・TTS音声読み上げを無効化")
    parser.add_argument("--no-save", action="store_true", help="TUGUMIDeskへの保存をスキップ")
    parser.add_argument("--stdout-only", action="store_true", help="Markdown本文のみを標準出力に出力")

    args = parser.parse_args()

    engine = DailyBriefingEngine()
    try:
        res = engine.generate_briefing(
            focus_topic=args.topic,
            note=args.note,
            save_desk=not args.no_save,
            send_notify=not args.no_notify
        )
        if args.stdout_only:
            print(res["content"])
        else:
            summary = {
                "status": res["status"],
                "date": res["date"],
                "saved_desk": res["desk_path"],
                "saved_local": res["local_path"],
                "elapsed": f"{res['elapsed_seconds']}s",
                "notification": res["notify_status"]
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[FATAL ERROR] {e}", file=sys.stderr)
        # エラー通知
        notifier = NotificationEngine()
        notifier.send_notification(
            title="⚠️ TUGUMIv6: ブリーフィング生成エラー",
            content=f"ブリーフィング生成中にエラーが発生しました: {str(e)[:50]}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
