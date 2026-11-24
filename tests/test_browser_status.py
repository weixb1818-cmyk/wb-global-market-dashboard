"""浏览器测试（审计第三轮技术修正 1）：前端状态严格映射。

要点：
- 仅在内存中构造测试快照并注入页面，不改动任何 data/ 真实数据文件；
- 内联当前真实的 app.js 渲染逻辑，测的是实际前端代码而非副本；
- ok/stale/missing/error 各自映射到确定文案；
- unknown / 未定义(undefined) / 空串 / 拼错值一律显示"状态未知，未验证"，
  绝不再出现旧的 `STATUS_TEXT[status] || "已更新"` 兜底所导致的误显示。

运行：python3 -m unittest tests.test_browser_status -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")

# (指示键, 注入的 status 值, 期望 badge 文案)
STATUS_CASES = [
    ("ok",        "ok",        "已更新"),
    ("stale",     "stale",     "数据延迟"),
    ("missing",   "missing",   "数据缺失"),
    ("error",     "error",     "更新失败"),
    ("unknown",   "unknown",   "状态未知，未验证"),
    ("undef",     None,        "状态未知，未验证"),   # JSON null -> JS undefined 值的等价缺失态
    ("empty",     "",          "状态未知，未验证"),
    ("typo",      "OK",        "状态未知，未验证"),   # 大小写不符也应判未知
]


def _indicator(name, status):
    return {
        "name": name,
        "group": "宏观",
        "status": status,
        "display_value": "100.00",
        "unit": "",
        "change_1": None,
        "change_1_text": "—",
        "change_20": None,
        "change_20_text": "—",
        "note": "",
        "as_of": "2026-11-23",
        "source": "test",
    }


def _build_html():
    indicators = {}
    for key, status, _ in STATUS_CASES:
        indicators[key] = _indicator("STATUS-" + key, status)
    snapshot = {
        "generated_at": "2026-11-23T00:00:00+09:00",
        "macro": {},
        "indicators": indicators,
        "failed_sources": [],
    }
    snap_js = "window.GLOBAL_MARKET_SNAPSHOT = " + json.dumps(
        snapshot, ensure_ascii=False) + ";"
    # 用最小 DOM 骨架承载 app.js 所需的全部节点，脚本改为内联真实 app.js。
    return """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<div class="stamp" id="stamp"></div>
<section class="macro-panel" id="macro-panel">
  <div class="macro-state" id="macro-state"></div>
  <div class="macro-why" id="macro-why"></div>
  <div class="uncertainty" id="macro-uncertainty"></div>
  <div class="data-note" id="data-note"></div>
</section>
<main id="board"></main>
<span id="failed-sources"></span>
<script>__SNAP__</script>
<script>__APP__</script>
</body></html>""".replace("__SNAP__", snap_js).replace("__APP__", APP_JS)


class TestBrowserStatusMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 环境不具备时跳过
            raise unittest.SkipTest(f"playwright 不可用: {exc}")
        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium",
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
        except Exception as exc:  # pragma: no cover
            cls._pw.stop()
            raise unittest.SkipTest(f"chromium 不可用: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def setUp(self):
        self.page = self._browser.new_page()
        self.page.set_content(_build_html())

    def tearDown(self):
        self.page.close()

    def _badge_text(self, key):
        # 按卡片名称定位，取该卡片内第一个 .badge 的文本。
        card = self.page.locator("article.card").filter(has_text="STATUS-" + key)
        self.assertEqual(card.count(), 1, f"未找到卡片 STATUS-{key}")
        return card.locator(".badge").first.inner_text()

    def test_known_status_texts(self):
        for key, status, expected in STATUS_CASES[:4]:
            self.assertEqual(self._badge_text(key), expected, key)

    def test_unknown_status_never_shows_updated(self):
        """核心断言：unknown 状态不显示"已更新"。"""
        self.assertEqual(self._badge_text("unknown"), "状态未知，未验证")
        self.assertNotIn("已更新", self._badge_text("unknown"))

    def test_undefined_status_never_shows_updated(self):
        """核心断言：未定义(null)状态不显示"已更新"。"""
        self.assertEqual(self._badge_text("undef"), "状态未知，未验证")
        self.assertNotIn("已更新", self._badge_text("undef"))

    def test_empty_and_typo_status_show_unknown(self):
        for key in ("empty", "typo"):
            self.assertEqual(self._badge_text(key), "状态未知，未验证", key)
            self.assertNotIn("已更新", self._badge_text(key), key)

    def test_unknown_badge_uses_unknown_class(self):
        """未知状态使用 unknown 样式类，不继承 ok 的绿标。"""
        card = self.page.locator("article.card").filter(has_text="STATUS-undef")
        cls = card.locator(".badge").first.get_attribute("class")
        self.assertIn("badge unknown", cls)
        self.assertNotIn("badge ok", cls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
