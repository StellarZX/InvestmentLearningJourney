"use strict";

const state = {
  lang: "zh",
  dca: null,
};

const translations = {
  zh: {
    dcaPageTitle: "每月定投分配决策",
    dcaPageSubtitle: "按估值/价格分位调整的月度计划：A股 ¥1,500 + 美股 ¥1,000（默认合计 ¥2,500，可调整）。",
    dcaEyebrow: "月度计划",
    dcaMonthlyTotal: "月度总投入（¥）",
    navIndices: "指数看板",
    navDca: "定投决策",
    navPortfolio: "持仓记录",
    navHoldings: "持仓应急",
    dcaRefresh: "重新计算",
    dcaRunHint: "每月 10 号：先运行 .\\.venv\\Scripts\\python.exe .\\02_IndexETF\\script.py --fetch-only，再打开本页查看当月分配。",
    dcaAsOf: "决策日期",
    dcaBudget: "月度预算",
    dcaFund: "基金",
    dcaCode: "代码",
    dcaQuota: "配额",
    dcaTracking: "跟踪指数",
    dcaPercentile: "历史分位",
    dcaZone: "区间",
    dcaMultiplier: "倍数",
    dcaAmount: "本月金额",
    dcaTotal: "合计",
    dcaRule: "规则：分位 <30% 买 1.5 倍，30%-70% 买 1.0 倍，>70% 买 0.5 倍，再归一化到月度预算。",
    groupCN: "A股长期指数（月度定投）",
    groupUS: "美股长期指数（每日 ¥10 定投）",
    zoneCheap: "便宜",
    zoneNeutral: "中性",
    zoneExpensive: "偏贵",
    zoneNone: "无数据",
    zoneFixed: "固定",
    sourceLegulegu: "乐咕乐股 PE(TTM) 历史分位",
    sourcePrice3y: "价格分位（近3年）",
    sourceProxy: "ETF 价格分位（近3年，代理）",
    sourceNone: "暂无数据，按 1.0 倍处理",
    proxyCsiDividend: "用中证红利ETF(515080)价格代理",
    proxyHsDlv: "用恒生红利低波ETF(159545)价格代理",
    notesZh: [
      "规则：分位 <30% 买 1.5 倍，30%-70% 买 1.0 倍，>70% 买 0.5 倍，再归一化到月度预算。",
      "A股与美股比例固定 60%/40%（默认 ¥1,500 + ¥1,000）；修改上方月度总投入后点“重新计算”。",
      "美股通过国内平台每日 ¥10 定投：标普500 = 摩根A + 摩根C；纳斯达克100 = 摩根A / 招商A / 华泰A；金额固定、不随估值调整。",
      "港股/美股/红利等无估值数据的标的用近 3 年价格分位作参考；金额为计划金额，不含手续费与申购限制。",
    ],
    unableToLoad: "无法加载数据",
  },
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function t(key) {
  return translations[state.lang][key] || key;
}

function applyTranslations() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("dcaPageTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
}

function zoneLabel(zone) {
  const key = { cheap: "zoneCheap", neutral: "zoneNeutral", expensive: "zoneExpensive", none: "zoneNone", fixed: "zoneFixed" }[zone];
  return key ? t(key) : zone;
}

function sourceLabel(item) {
  if (item.source_code) {
    const key = { legulegu_pe: "sourceLegulegu", price_3y: "sourcePrice3y", price_proxy: "sourceProxy", no_data: "sourceNone" }[item.source_code];
    if (key) return t(key);
  }
  return item.source;
}

function proxyNote(item) {
  if (state.lang === "zh" && item.index_slug) {
    const key = { csi_dividend: "proxyCsiDividend", hsi_dividend_lowvol: "proxyHsDlv" }[item.index_slug];
    if (key) return t(key);
  }
  return item.proxy_note;
}

function renderDca(payload) {
  const host = document.querySelector("#dcaGroups");
  if (!payload || !payload.groups) return;
  document.querySelector("#dcaError").classList.add("hidden");
  const currencySymbol = (g) => (g.currency === "CNY" ? "¥" : "€");
  host.innerHTML = payload.groups.map((g) => `
    <div class="dca-group">
      <div class="dca-group-header">
        <h4>${g.market === "cn" ? t("groupCN") : t("groupUS")}</h4>
        <span class="dca-budget">${t("dcaBudget")}: ${currencySymbol(g)}${fmt.format(g.budget)}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>${t("dcaFund")}</th>
              <th>${t("dcaCode")}</th>
              <th>${t("dcaQuota")}</th>
              <th>${t("dcaTracking")}</th>
              <th>${t("dcaPercentile")}</th>
              <th>${t("dcaZone")}</th>
              <th>${t("dcaMultiplier")}</th>
              <th>${t("dcaAmount")}</th>
            </tr>
          </thead>
          <tbody>
            ${g.items.map((item) => {
              const pct = item.percentile != null ? fmt.format(item.percentile) + "%" : "-";
              return `
                <tr>
                  <td>${item.name}</td>
                  <td>${item.code}</td>
                  <td>${item.quota_pct != null ? fmt.format(item.quota_pct) + "%" : "-"}</td>
                  <td>${item.tracking}</td>
                  <td>${pct}<div class="muted">${sourceLabel(item)}</div></td>
                  <td><span class="zone-chip zone-${item.zone}">${zoneLabel(item.zone)}</span></td>
                  <td>${fmt.format(item.multiplier)}×</td>
                  <td><strong>${currencySymbol(g)}${fmt.format(item.amount)}</strong></td>
                </tr>`;
            }).join("")}
            <tr class="dca-total">
              <td colspan="6">${t("dcaTotal")}</td>
              <td>${currencySymbol(g)}${fmt.format(g.total)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      ${g.items.some((i) => i.proxy_note)
        ? `<p class="muted">${g.items.filter((i) => i.proxy_note).map((i) => proxyNote(i)).join(state.lang === "zh" ? "；" : "; ")}</p>`
        : ""}
    </div>`).join("");
  document.querySelector("#dcaTitle").textContent = t("dcaPageTitle");
  document.querySelector("#dcaCaption").textContent = `${t("dcaAsOf")}: ${payload.as_of} · ${t("dcaRule")}`;
  const notes = document.querySelector("#dcaNotes");
  if (state.lang === "zh" && t("notesZh")) {
    notes.innerHTML = t("notesZh").map((n) => `<div>· ${n}</div>`).join("");
  } else if (payload.notes) {
    notes.innerHTML = payload.notes.map((n) => `<div>· ${n}</div>`).join("");
  } else {
    notes.innerHTML = "";
  }
}

async function loadDca() {
  try {
    const monthly = document.querySelector("#monthlyTotalInput").value;
    const url = monthly ? `/api/dca?monthly=${encodeURIComponent(monthly)}` : "/api/dca";
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: /api/dca`);
    const payload = await response.json();
    state.dca = payload;
    renderDca(payload);
  } catch (error) {
    const box = document.querySelector("#dcaError");
    box.textContent = `${t("unableToLoad")}: ${error.message}`;
    box.classList.remove("hidden");
  }
}

document.querySelector("#dcaRefreshButton").addEventListener("click", loadDca);

applyTranslations();
loadDca();
