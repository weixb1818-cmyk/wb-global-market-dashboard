/* 全球市场每日观察面板 — 仅负责呈现，不含任何数据生成或模拟逻辑 */
(function () {
  "use strict";

  var GROUP_ORDER = ["宏观", "美股", "大宗", "加密", "外汇"];
  var GROUP_DESC = {
    "宏观": "美元、利率、波动与信用",
    "美股": "指数本身，非 ETF",
    "大宗": "近月期货，单位按品种标注",
    "加密": "现货口径，24×7 市场",
    "外汇": "1 美元折合外币"
  };
  var STATUS_TEXT = {
    ok: "已更新", stale: "数据延迟", missing: "数据缺失", error: "更新失败"
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function directionClass(v) {
    if (v === null || v === undefined || isNaN(v)) return "flat";
    if (v > 0) return "up";
    if (v < 0) return "down";
    return "flat";
  }

  function formatStamp(s) {
    if (!s) return "—";
    var d = new Date(s);
    if (isNaN(d.getTime())) return s;
    var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function renderMacro(snapshot) {
    var macro = snapshot.macro || {};
    var panel = document.getElementById("macro-panel");
    if (macro.state === "insufficient") panel.classList.add("state-insufficient");
    document.getElementById("macro-state").textContent = macro.headline || "—";
    document.getElementById("macro-why").textContent = macro.why || "";
    document.getElementById("macro-uncertainty").textContent =
      "不确定因素：" + (macro.uncertainty || "—");
    document.getElementById("data-note").textContent = snapshot.data_note || "";

    var stamp = document.getElementById("stamp");
    stamp.innerHTML = "";
    stamp.appendChild(el("div", "", "快照生成（东京时间）"));
    stamp.appendChild(el("strong", "", formatStamp(snapshot.generated_at)));
  }

  function renderCard(item) {
    var card = el("article", "card");
    var head = el("div", "card-head");
    head.appendChild(el("div", "card-name", item.name));
    var badge = el("span", "badge " + (item.status || "ok"),
      STATUS_TEXT[item.status] || "已更新");
    // 右对齐标签容器：数据状态 badge 与报价性质标签竖排，互不影响。
    var tags = el("div", "head-tags");
    tags.appendChild(badge);
    // 报价性质独立标签（如近月期货“延迟报价·非实时可成交价”），
    // 与数据状态 badge 分离，避免把 realTime=false 误读为取数失败或实时可成交。
    if (item.quote_label) {
      tags.appendChild(el("span", "quote-tag", item.quote_label));
    }
    head.appendChild(tags);
    card.appendChild(head);

    var value = el("div", "card-value", item.display_value || "—");
    var unit = item.unit || "";
    if (unit && item.display_value && item.display_value.indexOf(unit) === -1) {
      value.appendChild(el("span", "unit", unit));
    }
    card.appendChild(value);

    var changes = el("div", "changes");
    var c1 = el("span", "", "日变化 ");
    c1.appendChild(el("b", directionClass(item.change_1), item.change_1_text || "—"));
    var c20 = el("span", "", "近20期 ");
    c20.appendChild(el("b", directionClass(item.change_20), item.change_20_text || "—"));
    changes.appendChild(c1);
    changes.appendChild(c20);
    card.appendChild(changes);

    card.appendChild(el("div", "note", item.note || "—"));

    var foot = el("div", "card-foot");
    foot.appendChild(el("span", "", "截至 " + (item.as_of || "未知日期")));
    foot.appendChild(el("span", "", item.source || "未知来源"));
    card.appendChild(foot);
    return card;
  }

  function renderBoard(snapshot) {
    var board = document.getElementById("board");
    board.innerHTML = "";
    var indicators = snapshot.indicators || {};
    var byGroup = {};
    GROUP_ORDER.forEach(function (g) { byGroup[g] = []; });
    Object.keys(indicators).forEach(function (id) {
      var it = indicators[id];
      if (!byGroup[it.group]) byGroup[it.group] = [];
      byGroup[it.group].push(it);
    });

    GROUP_ORDER.forEach(function (g) {
      var items = byGroup[g] || [];
      if (!items.length) return;
      var section = el("section", "group");
      var head = el("div", "group-head");
      head.appendChild(el("h2", "", g));
      head.appendChild(el("span", "", GROUP_DESC[g] || ""));
      section.appendChild(head);
      var grid = el("div", "grid");
      items.forEach(function (it) { grid.appendChild(renderCard(it)); });
      section.appendChild(grid);
      board.appendChild(section);
    });
  }

  function renderFailure(snapshot) {
    var node = document.getElementById("failed-sources");
    var fails = snapshot.failed_sources || [];
    node.textContent = fails.length ? "本次取数异常来源：" + fails.join("、") : "本次各数据源取数正常";
  }

  function showFatal(message) {
    var board = document.getElementById("board");
    board.innerHTML = "";
    var box = el("div", "macro-panel");
    box.appendChild(el("div", "macro-state", "快照不可用"));
    box.appendChild(el("div", "macro-why", message));
    board.appendChild(box);
  }

  function boot() {
    if (window.GLOBAL_MARKET_SNAPSHOT) {
      renderAll(window.GLOBAL_MARKET_SNAPSHOT);
      return;
    }
    var fallbackUrl = "data/snapshot.json";
    try {
      var code = new URLSearchParams(location.search).get("sharecode");
      if (code) fallbackUrl += "?sharecode=" + encodeURIComponent(code);
    } catch (e) {}
    fetch(fallbackUrl, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("无法读取 data/snapshot.json（HTTP " + r.status + "）");
        return r.json();
      })
      .then(renderAll)
      .catch(function (err) {
        showFatal("请先运行 python3 scripts/update_data.py 生成快照；错误信息：" + err.message);
      });
  }

  function renderAll(snapshot) {
    renderMacro(snapshot);
    renderBoard(snapshot);
    renderFailure(snapshot);
  }

  boot();
}());
