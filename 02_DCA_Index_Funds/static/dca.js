"use strict";

const state = {
  lang: localStorage.getItem("marketDashboardLanguage") || "en",
  dca: null,
};

const translations = {
  en: {
    dcaPageTitle: "Monthly DCA Allocation",
    dcaPageSubtitle: "Valuation-based monthly plan: ¥2,000 (CNY) + €50 (EUR).",
    dcaEyebrow: "Monthly plan",
    navIndices: "Index Dashboard",
    navDca: "DCA Decision",
    navHoldings: "Emergency Review",
    dcaRefresh: "Recalculate",
    dcaRunHint: "Monthly flow: run .\\.venv\\Scripts\\python.exe .\\02_DCA_Index_Funds\\script.py --fetch-only on the 10th, then open this page.",
    dcaAsOf: "As of",
    dcaBudget: "Monthly budget",
    dcaFund: "Fund",
    dcaCode: "Code",
    dcaQuota: "Quota",
    dcaTracking: "Tracking index",
    dcaPercentile: "Percentile",
    dcaZone: "Zone",
    dcaMultiplier: "Multiplier",
    dcaAmount: "Amount",
    dcaTotal: "Total",
    dcaRule: "Rule: percentile <30% → 1.5×, 30-70% → 1.0×, >70% → 0.5×, normalized to the budget.",
    groupCN: "Bank of China App (CNY)",
    groupIBKR: "Interactive Brokers (EUR)",
    zoneCheap: "Cheap",
    zoneNeutral: "Neutral",
    zoneExpensive: "Expensive",
    zoneNone: "N/A",
    sourceLegulegu: "Legulegu PE(TTM) history percentile",
    sourcePrice3y: "3-year price percentile",
    sourceProxy: "3-year price percentile (ETF proxy)",
    sourceNone: "No data, treated as 1.0×",
    proxyCsiDividend: "Price proxy: CSI Dividend ETF (515080)",
    proxyHsDlv: "Price proxy: HS Dividend Low Vol ETF (159545)",
    languageButton: "中文",
    unableToLoad: "Unable to load data",
  },
  zh: {
    dcaPageTitle: "每月定投分配决策",
    dcaPageSubtitle: "按估值/价格分位调整的月度计划：人民币 ¥2,000 + 欧元 €50。",
    dcaEyebrow: "月度计划",
    navIndices: "指数看板",
    navDca: "定投决策",
    navHoldings: "持仓应急",
    dcaRefresh: "重新计算",
    dcaRunHint: "每月 10 号：先运行 .\\.venv\\Scripts\\python.exe .\\02_DCA_Index_Funds\\script.py --fetch-only，再打开本页查看当月分配。",
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
    groupCN: "中国银行 App（人民币）",
    groupIBKR: "盈透证券 IBKR（欧元）",
    zoneCheap: "便宜",
    zoneNeutral: "中性",
    zoneExpensive: "偏贵",
    zoneNone: "无数据",
    sourceLegulegu: "乐咕乐股 PE(TTM) 历史分位",
    sourcePrice3y: "价格分位（近3年）",
    sourceProxy: "ETF 价格分位（近3年，代理）",
    sourceNone: "暂无数据，按 1.0 倍处理",
    proxyCsiDividend: "用中证红利ETF(515080)价格代理",
    proxyHsDlv: "用恒生红利低波ETF(159545)价格代理",
    notesZh: [
      "规则：分位 <30% 买 1.5 倍，30%-70% 买 1.0 倍，>70% 买 0.5 倍，再归一化到月度预算。",
      "港股/美股/红利等无估值数据的标的用近 3 年价格分位替代，仅供参考。",
      "金额为计划金额，不含手续费与申购限制；QDII 基金可能存在限购，请以 App 实际为准。",
    ],
    languageButton: "English",
    unableToLoad: "无法加载数据",
  },
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function t(key) {
  return translations[state.lang][key] || translations.en[key] || key;
}

function applyTranslations() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("dcaPageTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelector("#languageButton").textContent = t("languageButton");
}

function zoneLabel(zone) {
  const key = { cheap: "zoneCheap", neutral: "zoneNeutral", expensive: "zoneExpensive", none: "zoneNone" }[zone];
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
        <h4>${g.market === "cn" ? t("groupCN") : t("groupIBKR")}</h4>
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
    const response = await fetch("/api/dca");
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

document.querySelector("#languageButton").addEventListener("click", () => {
  state.lang = state.lang === "en" ? "zh" : "en";
  localStorage.setItem("marketDashboardLanguage", state.lang);
  applyTranslations();
  if (state.dca) renderDca(state.dca);
});

document.querySelector("#dcaRefreshButton").addEventListener("click", loadDca);

applyTranslations();
loadDca();
