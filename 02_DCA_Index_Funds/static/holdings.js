"use strict";

const state = {
  lang: localStorage.getItem("marketDashboardLanguage") || "en",
  payload: null,
};

const translations = {
  en: {
    holdingsPageTitle: "Emergency Position Review",
    holdingsPageSubtitle: "Which holdings to sell first if you need cash in a crash.",
    holdingsEyebrow: "Crash scenario",
    navIndices: "Index Dashboard",
    navDca: "DCA Decision",
    navPortfolio: "Portfolio",
    navHoldings: "Emergency Review",
    holdingsSourceNote: "Holdings are read from the repository root README.md.",
    holdingsRefresh: "Recalculate",
    holdingsTableTitle: "Position Review",
    holdingsOrderCaption: "Sorted by sell priority (trend 40% / momentum 30% / valuation 30%).",
    holdingsOrderTitle: "Suggested Sell Order",
    holdingsOrderNote: "From a quality perspective. For urgent cash, follow liquidity first.",
    holdingsNotesTitle: "How to read this",
    hFund: "Fund",
    hCode: "Code",
    hClass: "Role",
    hPosition: "Position",
    hTrend: "Trend",
    hMomentum: "6M",
    hDrawdown: "Drawdown",
    hValuation: "Valuation",
    hScore: "Sell Score",
    hTier: "Tier",
    hLiquidity: "Liquidity",
    hRecommendation: "Recommendation",
    hAsOf: "As of",
    hCash: "Cash buffer",
    hPositions: "positions",
    hScoreSub: "Higher = sell first",
    classCore: "Core holding",
    classSatellite: "Satellite",
    classUnknown: "Unknown",
    trendAbove: "Above 200-day MA",
    trendBelow: "Below 200-day MA",
    sourcePe: "PE(TTM) history percentile",
    sourcePrice3y: "3-year price percentile",
    sourceNone: "No data",
    liqFast: "Fast: redemption T+1~T+3",
    liqSlow: "Slow: QDII redemption ~T+7~T+10",
    liqMedium: "Medium: same-day sell, T+2 settlement",
    liqCash: "Settled",
    liqUnknown: "Unknown",
    cashRec: "Cash is the emergency buffer; use it before selling funds",
    disclaimerZh: "Decision reference only; not investment advice.",
    tierHigh: "Sell first",
    tierMedium: "May sell",
    tierLow: "Keep",
    tierCash: "Keep cash",
    tierNone: "No data",
    unableToLoad: "Unable to load data",
    languageButton: "中文",
  },
  zh: {
    holdingsPageTitle: "持仓应急评估",
    holdingsPageSubtitle: "大跌需要现金时，先卖哪些、保留哪些。",
    holdingsEyebrow: "应急场景",
    navIndices: "指数看板",
    navDca: "定投决策",
    navPortfolio: "持仓记录",
    navHoldings: "持仓应急",
    holdingsSourceNote: "持仓来自根目录 README.md（唯一事实来源）。",
    holdingsRefresh: "重新计算",
    holdingsTableTitle: "持仓评估",
    holdingsOrderCaption: "按卖出优先级排序（趋势 40% + 动量 30% + 估值 30%）。",
    holdingsOrderTitle: "建议卖出顺序",
    holdingsOrderNote: "质地角度排序；若急需现金，请先按到账速度考虑。",
    holdingsNotesTitle: "如何解读",
    hFund: "基金",
    hCode: "代码",
    hClass: "角色",
    hPosition: "持仓",
    hTrend: "趋势",
    hMomentum: "近6月",
    hDrawdown: "回撤",
    hValuation: "估值分位",
    hScore: "卖出优先级",
    hTier: "评级",
    hLiquidity: "到账速度",
    hRecommendation: "建议",
    hAsOf: "数据日期",
    hCash: "现金缓冲",
    hPositions: "只",
    hScoreSub: "越高越建议先卖",
    classCore: "核心底仓",
    classSatellite: "卫星配置",
    classUnknown: "未知",
    trendAbove: "多头（站上200日线）",
    trendBelow: "空头（跌破200日线）",
    sourcePe: "PE(TTM) 历史分位",
    sourcePrice3y: "价格分位（近3年）",
    sourceNone: "暂无数据",
    liqFast: "快：赎回 T+1~T+3 到账",
    liqSlow: "慢：QDII 赎回约 T+7~T+10 到账",
    liqMedium: "中：卖出即时锁价，T+2 交割",
    liqCash: "已到账",
    liqUnknown: "未知",
    cashRec: "现金是应急缓冲，优先使用它而不是卖基金",
    disclaimerZh: "决策参考，非投资建议。",
    notesZh: [
      "卖出优先级 = 40% 趋势（相对200日线）+ 30% 动量（近6个月）+ 30% 估值/价格分位；分数越高越建议先卖。",
      "急用现金时优先考虑到账速度：先用现金缓冲，再卖 A 股基金（T+1~T+3 到账），IBKR 卖出 T+2 交割，QDII 赎回最慢（T+7~T+10）。",
      "大跌中跌幅已深的持仓往往更接近阶段性底部，单纯因下跌而割肉需谨慎；本表反映的是趋势/动量/估值状态，不是买卖时点建议。",
      "本页面仅为决策参考框架，不构成投资建议；实际平仓请结合你的现金需求、持有成本与税务情况。",
    ],
    tierHigh: "优先卖出",
    tierMedium: "可考虑卖出",
    tierLow: "继续持有",
    tierCash: "保留现金",
    tierNone: "数据不足",
    unableToLoad: "无法加载数据",
    languageButton: "English",
  },
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function t(key) {
  return translations[state.lang][key] || translations.en[key] || key;
}

function applyTranslations() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("holdingsPageTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelector("#languageButton").textContent = t("languageButton");
}

function tierLabel(level, rawLabel) {
  return { high: t("tierHigh"), medium: t("tierMedium"), low: t("tierLow"), cash: t("tierCash"), none: t("tierNone") }[level] || rawLabel;
}

function positionClassLabel(item) {
  const map = { core: t("classCore"), satellite: t("classSatellite"), cash: t("hCash"), unknown: t("classUnknown") };
  return (item.position_class_code && map[item.position_class_code]) || item.position_class;
}

function trendLabel(item) {
  if (item.trend === "above") return t("trendAbove");
  if (item.trend === "below") return t("trendBelow");
  return item.trend_label || "-";
}

function sourceLabel(item) {
  const key = { pe_history: "sourcePe", price_3y: "sourcePrice3y", none: "sourceNone" }[item.valuation_source_code];
  return key ? t(key) : (item.valuation_source || "");
}

function liquidityLabel(item) {
  const map = { fast: t("liqFast"), slow: t("liqSlow"), medium: t("liqMedium"), cash: t("liqCash"), none: t("liqUnknown") };
  return (item.liquidity.level && map[item.liquidity.level]) || item.liquidity.label;
}

function recommendationZh(item) {
  if (item.position_class_code === "cash") return t("cashRec");
  if (item.tier_level === "none") return "数据不足，请手动评估";
  const core = item.is_core ? "（核心底仓）" : "";
  if (item.tier_level === "high") return core ? "优先卖出（虽是核心，但趋势与估值均弱）" : "优先卖出";
  if (item.tier_level === "medium") return core ? "可考虑卖出（核心底仓，谨慎权衡）" : "可考虑卖出";
  return core ? "继续持有（核心底仓）" : "继续持有";
}

function fmtPct(value) {
  return value == null ? "-" : fmt.format(value) + "%";
}

function renderHoldings(payload) {
  state.payload = payload;
  document.querySelector("#holdingsError").classList.add("hidden");
  document.querySelector("#holdingsTitle").textContent = t("holdingsPageTitle");
  document.querySelector("#holdingsCaption").textContent = `${t("hAsOf")}: ${payload.as_of} · ${payload.summary_source}`;

  const cashTotal = payload.cash.reduce((s, c) => s + (c.position_amount || 0), 0);
  const overview = [
    [t("hFund"), payload.items.length + payload.cash.length + " " + t("hPositions"), ""],
    [t("hCash"), payload.cash.length ? `${payload.cash[0].code} ${fmt.format(cashTotal)}` : "-", ""],
    [t("hScore"), "0-100", t("hScoreSub")],
  ];
  document.querySelector("#holdingsOverview").innerHTML = overview
    .map(([label, value, sub]) => `
      <div class="metric-card">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        <div class="sub">${sub}</div>
      </div>`)
    .join("");

  const body = document.querySelector("#holdingsBody");
  body.innerHTML = payload.items.map((item) => {
    const score = item.sell_score != null ? `<strong>${fmt.format(item.sell_score)}</strong>` : "-";
    return `
      <tr>
        <td>${item.fund}</td>
        <td>${item.code}</td>
        <td>${positionClassLabel(item)}</td>
        <td>${item.position_raw}</td>
        <td>${trendLabel(item)}<div class="muted">${fmtPct(item.ma200_distance_pct)}</div></td>
        <td class="${item.ret_6m_pct != null && item.ret_6m_pct < 0 ? "negative" : "positive"}">${fmtPct(item.ret_6m_pct)}</td>
        <td>${fmtPct(item.drawdown_pct)}</td>
        <td>${fmtPct(item.valuation_pct)}<div class="muted">${sourceLabel(item)}</div></td>
        <td>${score}</td>
        <td><span class="zone-chip tier-${item.tier_level}">${tierLabel(item.tier_level, item.tier)}</span></td>
        <td>${liquidityLabel(item)}</td>
        <td>${state.lang === "zh" ? recommendationZh(item) : item.recommendation}</td>
      </tr>`;
  }).join("");

  const order = document.querySelector("#holdingsOrder");
  const scored = payload.items.filter((i) => i.sell_score != null);
  order.innerHTML = scored.length
    ? scored.map((item, i) => `<li>${
        state.lang === "zh"
          ? `${i + 1}. ${item.fund}（优先级 ${fmt.format(item.sell_score)}，${tierLabel(item.tier_level)}）`
          : payload.sell_order[i]
      }</li>`).join("")
    : `<li>${tierLabel("none")}</li>`;

  const cash = document.querySelector("#holdingsCash");
  cash.innerHTML = payload.cash.length
    ? payload.cash.map((c) => `<div class="holdings-cash-item"><strong>${t("hCash")}: ${c.position_raw}</strong> — ${state.lang === "zh" ? t("cashRec") : c.recommendation}</div>`).join("")
    : "";

  const notes = document.querySelector("#holdingsNotes");
  notes.innerHTML = (state.lang === "zh" && t("notesZh")
    ? t("notesZh")
    : payload.notes
  ).map((n) => `<li>${n}</li>`).join("");
  document.querySelector("#holdingsDisclaimer").textContent = state.lang === "zh" ? t("disclaimerZh") : payload.disclaimer;
}

async function loadHoldings() {
  try {
    const response = await fetch("/api/holdings");
    if (!response.ok) throw new Error(`Request failed: /api/holdings`);
    const payload = await response.json();
    renderHoldings(payload);
  } catch (error) {
    const box = document.querySelector("#holdingsError");
    box.textContent = `${t("unableToLoad")}: ${error.message}`;
    box.classList.remove("hidden");
  }
}

document.querySelector("#languageButton").addEventListener("click", () => {
  state.lang = state.lang === "en" ? "zh" : "en";
  localStorage.setItem("marketDashboardLanguage", state.lang);
  applyTranslations();
  if (state.payload) renderHoldings(state.payload);
});

document.querySelector("#holdingsRefreshButton").addEventListener("click", loadHoldings);

applyTranslations();
loadHoldings();
