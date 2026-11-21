#!/usr/bin/env python3
"""把 AUDIT.md 渲染为可在浏览器直接阅读的审计页面 audit.html。"""
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
md_text = (ROOT / "AUDIT.md").read_text(encoding="utf-8")
body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])

SOURCE_LINKS = [
    ("index.html", "页面入口"),
    ("styles.css", "样式"),
    ("app.js", "前端渲染"),
    ("core.py", "核心逻辑（单位/状态/解读）"),
    ("config.json", "指标定义与阈值"),
    ("scripts/update_data.py", "取数与快照生成"),
    ("tests/test_core.py", "26 项验收测试"),
    ("README.md", "运行与部署说明"),
    ("AUDIT.md", "本审计文档源文件"),
    ("data/snapshot.json", "当前真实快照"),
    ("data/history.json", "滚动历史"),
    ("requirements.txt", "依赖"),
    ("update-workflow.yml", "每日自动更新流程"),
    ("data/snapshot.js", "供本地双击打开的快照包装"),
]

links = "\n".join(
    f'<li><a href="{href}" target="_blank" rel="noopener">{href}</a>'
    f'<span class="desc">{desc}</span></li>'
    for href, desc in SOURCE_LINKS
)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>审计中心 · 全球市场每日观察面板</title>
<style>
  :root {{ --navy:#0b2545; --blue:#1b5fa8; --line:#d8e2ef; --bg:#f3f7fc; --ink:#16283f; --muted:#5b7089; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    font-size:14px; line-height:1.7; }}
  header {{ background:linear-gradient(100deg,var(--navy),#13395e); color:#fff; padding:18px 24px; }}
  header h1 {{ margin:0; font-size:22px; }}
  header p {{ margin:6px 0 0; color:#bcd4ec; font-size:13px; }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:18px 20px 40px; }}
  .panel {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:16px 20px; }}
  .sources {{ margin-bottom:16px; }}
  .sources h2 {{ margin:0 0 8px; font-size:16px; color:var(--navy); }}
  .sources ul {{ list-style:none; margin:0; padding:0; display:grid;
    grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:6px 18px; }}
  .sources li {{ display:flex; align-items:baseline; gap:8px; font-size:12.5px;
    border-bottom:1px dashed var(--line); padding:3px 0; }}
  .sources a {{ color:var(--blue); text-decoration:none; font-weight:600; word-break:break-all; }}
  .sources a:hover {{ text-decoration:underline; }}
  .desc {{ color:var(--muted); font-size:11px; white-space:nowrap; }}
  .doc table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:12.5px; }}
  .doc th,.doc td {{ border:1px solid var(--line); padding:7px 9px; text-align:left; vertical-align:top; }}
  .doc th {{ background:var(--bg); color:var(--navy); }}
  .doc h2 {{ margin-top:28px; font-size:17px; color:var(--navy);
    border-left:4px solid var(--blue); padding-left:10px; }}
  .doc h3 {{ margin-top:22px; font-size:15px; color:#13395e; }}
  .doc code {{ background:#eef3f9; padding:1px 4px; border-radius:3px; font-size:12px; }}
  .doc pre {{ background:#0f2338; color:#d7e6f6; padding:12px; border-radius:6px; overflow:auto; }}
  .doc blockquote {{ border-left:3px solid #7aa8d8; margin:12px 0; padding:4px 12px; color:#466; background:#f6fafe; }}
  footer {{ margin-top:20px; font-size:11px; color:var(--muted); text-align:center; }}
  @media(max-width:560px){{ .doc table{{font-size:11px;}} .sources li{{flex-direction:column;gap:2px;}} }}
</style>
<script>
// 把当前分享链接中的 sharecode 自动透传到所有站内直链，避免点击后因缺少凭据被网关拦截。
// 不硬编码具体码值：分享链接更换 sharecode 后可自适应。
function __passShareCode() {{
  try {{
    var code = new URLSearchParams(location.search).get('sharecode');
    if (!code) return;
    document.querySelectorAll('a[href]').forEach(function (a) {{
      var href = a.getAttribute('href');
      if (!href || /^(https?:|#|mailto:)/i.test(href)) return;
      var u = new URL(href, location.href);
      if (!u.searchParams.get('sharecode')) u.searchParams.set('sharecode', code);
      a.setAttribute('href', u.pathname + u.search);
    }});
  }} catch (e) {{}}
}}
if (document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', __passShareCode);
else __passShareCode();
</script>
</head>
<body>
<header>
  <h1>审计中心 · 全球市场每日观察面板</h1>
  <p>逐指标数据源与计算方法 · 阈值可配置 · 全部源码与测试数据公开可下载 · 版本 V1.0 / P0</p>
</header>
<div class="wrap">
  <section class="panel sources">
    <h2>源码与数据入口（点击直接查看原始文件）</h2>
    <ul>{links}</ul>
  </section>
  <section class="panel doc">
    {body}
  </section>
  <footer>本文由 scripts/build_audit_page.py 从 AUDIT.md 自动生成；以源码与快照实际字段为准。</footer>
</div>
</body>
</html>
"""

(ROOT / "audit.html").write_text(html, encoding="utf-8")
print("已生成", ROOT / "audit.html")
