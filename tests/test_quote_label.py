"""审计 WB 第 2 项：黄金/WTI/铜延迟报价独立标签测试。

要点：
- 近月期货 realTime=false -> 独立“延迟报价”标签；
- 标签与 status 语义独立，不因延迟报价把正常报价标 stale；
- 真实报价日期由 as_of 单独承载，标签内不含日期；
- 数据源未提供可靠实时属性时不擅自标“实时”。
运行：python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import quote_label  # noqa: E402
from core import load_config  # noqa: E402

CFG = load_config()
DELAYED = ("gold", "wti", "copper")
LABEL = "延迟报价·非实时可成交价"


class TestQuoteLabel(unittest.TestCase):
    def test_delayed_indicators_have_label(self):
        for ind_id in DELAYED:
            self.assertEqual(quote_label(ind_id, CFG), LABEL, ind_id)

    def test_none_delayed_indicators_have_no_label(self):
        for ind_id in ("dxy", "us2y", "sp500", "nasdaq100", "btc", "eth",
                       "usdjpy", "hy_oas", "vix"):
            self.assertIsNone(quote_label(ind_id, CFG), ind_id)

    def test_label_independent_of_status(self):
        """标签与 status 分离：正常/延迟状态都保留报价性质标签，不混淆两概念。"""
        for st in ("ok", "stale", "missing", "error"):
            self.assertEqual(quote_label("gold", CFG, st), LABEL)

    def test_label_has_no_date(self):
        """标签仅描述报价性质，真实报价日期由 as_of 字段单独展示。"""
        lab = quote_label("wti", CFG)
        self.assertNotIn("2026", lab)
        self.assertNotIn("-", lab)

    def test_no_false_realtime_claim(self):
        """不做未经证实的“实时”标注；标签措辞明确为延迟、非实时可成交。"""
        lab = quote_label("copper", CFG)
        self.assertIn("延迟", lab)
        self.assertIn("非实时可成交", lab)
        self.assertNotIn("实时可成交价", lab.replace("非实时可成交价", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
