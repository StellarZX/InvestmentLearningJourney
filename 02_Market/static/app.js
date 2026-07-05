const state = {
  indices: [],
  selectedSlug: null,
  records: [],
  valuations: [],
  assessments: [],
  currentIndex: null,
  lang: localStorage.getItem("marketDashboardLanguage") || "en",
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const translations = {
  en: {
    appTitle: "Market Index Dashboard",
    appSubtitle: "Major global indices, stored locally by year.",
    eyebrow: "Local market data",
    loading: "Loading...",
    range: "Range",
    range1y: "1Y",
    range3y: "3Y",
    range5y: "5Y",
    rangeAll: "All",
    language: "Language",
    reload: "Reload",
    closePrice: "Close Price",
    valuationMetrics: "Valuation & Assessment",
    metric: "Metric",
    earningsYield: "Earnings Yield",
    peTtm: "P/E TTM",
    pb: "P/B",
    valuationUnavailable: "Assessment history is not available for this index yet.",
    latestRecords: "Latest Records",
    recordsSubtitle: "Daily OHLC data from local CSV files.",
    date: "Date",
    open: "Open",
    high: "High",
    low: "Low",
    close: "Close",
    volume: "Volume",
    latestClose: "Latest Close",
    dailyChange: "Daily Change",
    totalChange: "Total Change",
    records: "Records",
    tradingDays: "trading days",
    valuationNoCsv: "No assessment data is available for this index.",
    assessmentScore: "Composite Assessment Score",
    assessmentNote: "Higher score means the index has a more attractive combination of valuation, price position, drawdown, and trend.",
    adviceTitle: "Extra investment suggestion",
    adviceHigh: "The composite score is high. If this fits your allocation plan, it may be reasonable to consider an extra contribution.",
    adviceMedium: "The composite score is neutral. Consider waiting, observing, or adding only a small amount through your normal dollar-cost averaging plan.",
    adviceLow: "The composite score is low. It may be better to avoid extra contributions for now and follow the regular plan.",
    adviceUnavailable: "No score is available yet. Keep the regular plan and wait for more data.",
    confidenceValuation: "Valuation-supported score",
    confidencePriceOnly: "Price-only score",
    method: "Method",
    scoreBreakdown: "Breakdown",
    valuationScore: "Valuation",
    priceScore: "Price position",
    drawdownScore: "Drawdown",
    trendScore: "Trend",
    recordsCount: "records",
    unableToLoad: "Unable to load data",
    to: "to",
    languageButton: "中文",
    valuationAria: "Valuation metric chart",
    assessmentAria: "Composite assessment score chart",
  },
  zh: {
    appTitle: "市场指数仪表盘",
    appSubtitle: "主要全球指数数据，按年份存储在本地。",
    eyebrow: "本地市场数据",
    loading: "加载中...",
    range: "范围",
    range1y: "1年",
    range3y: "3年",
    range5y: "5年",
    rangeAll: "全部",
    language: "语言",
    reload: "刷新",
    closePrice: "收盘价",
    valuationMetrics: "估值与投入评估",
    metric: "指标",
    earningsYield: "盈利收益率",
    peTtm: "滚动市盈率",
    pb: "市净率",
    valuationUnavailable: "该指数暂时没有可用的评估历史数据。",
    latestRecords: "最新记录",
    recordsSubtitle: "来自本地 CSV 文件的每日 OHLC 数据。",
    date: "日期",
    open: "开盘",
    high: "最高",
    low: "最低",
    close: "收盘",
    volume: "成交量",
    latestClose: "最新收盘",
    dailyChange: "日涨跌",
    totalChange: "区间涨跌",
    records: "记录数",
    tradingDays: "个交易日",
    valuationNoCsv: "该指数暂无评估数据。",
    assessmentScore: "综合评估评分",
    assessmentNote: "分数越高，表示估值、价格位置、回撤和趋势组合越有吸引力。",
    adviceTitle: "额外投入建议",
    adviceHigh: "当前综合评分较高。如果符合你的资产配置计划，可以考虑额外投入。",
    adviceMedium: "当前综合评分中性。可以继续观察，或只按照原定定投计划小额投入。",
    adviceLow: "当前综合评分较低。此时更适合暂缓额外投入，继续执行常规定投计划。",
    adviceUnavailable: "暂时没有可用评分。建议先继续执行常规计划，等待更多数据。",
    confidenceValuation: "含估值数据的评分",
    confidencePriceOnly: "仅基于价格的评分",
    method: "计算方法",
    scoreBreakdown: "拆分",
    valuationScore: "估值",
    priceScore: "价格位置",
    drawdownScore: "回撤",
    trendScore: "趋势",
    recordsCount: "条记录",
    unableToLoad: "无法加载数据",
    to: "至",
    languageButton: "English",
    valuationAria: "估值指标走势图",
    assessmentAria: "综合评估评分走势图",
  },
};

const indexTranslations = {
  sp500: "标普500",
  nasdaq_composite: "纳斯达克综合指数",
  dow_jones: "道琼斯工业平均指数",
  nasdaq_100: "纳斯达克100",
  hang_seng: "恒生指数",
  csi_300: "沪深300",
  shanghai_composite: "上证指数",
  shenzhen_component: "深证成指",
  nikkei_225: "日经225",
  ftse_100: "英国富时100",
  dax: "德国DAX",
};

const regionTranslations = {
  "United States": "美国",
  "Hong Kong": "香港",
  China: "中国",
  Japan: "日本",
  "United Kingdom": "英国",
  Germany: "德国",
};

function t(key) {
  return translations[state.lang][key] || translations.en[key] || key;
}

function indexName(item) {
  return state.lang === "zh" ? (indexTranslations[item.slug] || item.name) : item.name;
}

function regionName(region) {
  return state.lang === "zh" ? (regionTranslations[region] || region) : region;
}

function applyTranslations() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("appTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelector("#languageButton").textContent = t("languageButton");
  document.querySelector("#valuationChart").setAttribute("aria-label", t("valuationAria"));
  document.querySelector("#assessmentChart").setAttribute("aria-label", t("assessmentAria"));
}

function valueClass(value) {
  return value >= 0 ? "positive" : "negative";
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return fmt.format(Number(value));
}

function formatAxisNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${url}`);
  return response.json();
}

function renderIndexList() {
  const list = document.querySelector("#indexList");
  list.innerHTML = state.indices.map((item) => `
    <button class="index-button ${item.slug === state.selectedSlug ? "active" : ""}" data-slug="${item.slug}">
      <strong>${indexName(item)}</strong>
    </button>
  `).join("");
  list.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => selectIndex(button.dataset.slug));
  });
}

function renderSummary(index) {
  const grid = document.querySelector("#summaryGrid");
  grid.innerHTML = `
    <article class="metric"><span>${t("latestClose")}</span><strong>${formatNumber(index.latest_close)}</strong></article>
    <article class="metric"><span>${t("dailyChange")}</span><strong class="${valueClass(index.daily_change || 0)}">${formatNumber(index.daily_change)} (${formatNumber(index.daily_change_pct)}%)</strong></article>
    <article class="metric"><span>${t("totalChange")}</span><strong class="${valueClass(index.total_change_pct || 0)}">${formatNumber(index.total_change_pct)}%</strong></article>
    <article class="metric"><span>${t("records")}</span><strong>${formatNumber(index.rows)}</strong></article>
  `;
  document.querySelector("#selectedName").textContent = indexName(index);
  document.querySelector("#selectedMeta").textContent = `${regionName(index.region)} · ${index.symbol} · ${index.currency} · ${index.first_date} ${t("to")} ${index.last_date}`;
}

function metricLabel(metric) {
  return {
    earnings_yield: `${t("earningsYield")} (%)`,
    pe_ttm: t("peTtm"),
    pb: t("pb"),
    close: t("closePrice"),
  }[metric] || metric;
}

function renderSingleAxisChart(svg, records, field, color) {
  svg.innerHTML = "";
  const usable = records
    .map((row) => ({ date: row.date, value: Number(row[field]) }))
    .filter((row) => !Number.isNaN(row.value));
  if (usable.length < 2) return false;

  const width = svg.clientWidth || 900;
  const height = svg.clientHeight || 320;
  const margin = { top: 18, right: 28, bottom: 34, left: 74 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = usable.map((row) => row.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = (max - min || Math.max(Math.abs(max), 1)) * 0.08;
  const yMin = min - padding;
  const yMax = max + padding;
  const span = yMax - yMin || 1;
  const x = (i) => margin.left + (i / (usable.length - 1)) * innerWidth;
  const y = (value) => margin.top + (1 - (value - yMin) / span) * innerHeight;
  const points = usable.map((row, i) => `${x(i)},${y(row.value)}`).join(" ");
  const ns = "http://www.w3.org/2000/svg";
  const el = (name, attrs = {}) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };

  [0, 0.25, 0.5, 0.75, 1].forEach((tick) => {
    const gy = margin.top + tick * innerHeight;
    svg.appendChild(el("line", { x1: margin.left, y1: gy, x2: width - margin.right, y2: gy, stroke: "#e6eaf0" }));
    const label = yMax - tick * span;
    const text = el("text", { x: margin.left - 10, y: gy + 4, fill: "#667085", "font-size": "12", "text-anchor": "end" });
    text.textContent = formatAxisNumber(label);
    svg.appendChild(text);
  });

  svg.appendChild(el("polyline", {
    points,
    fill: "none",
    stroke: color,
    "stroke-width": "2.5",
    "stroke-linejoin": "round",
    "stroke-linecap": "round",
  }));

  const leftLabel = el("text", { x: margin.left, y: height - 10, fill: "#667085", "font-size": "12" });
  leftLabel.textContent = usable[0].date;
  const rightLabel = el("text", { x: width - margin.right, y: height - 10, fill: "#667085", "font-size": "12", "text-anchor": "end" });
  rightLabel.textContent = usable[usable.length - 1].date;
  svg.appendChild(leftLabel);
  svg.appendChild(rightLabel);
  return true;
}

function renderValuationChart() {
  const shell = document.querySelector("#valuationShell");
  const empty = document.querySelector("#valuationEmpty");
  const caption = document.querySelector("#valuationCaption");
  const valuationSvg = document.querySelector("#valuationChart");
  const assessmentSvg = document.querySelector("#assessmentChart");
  let metric = document.querySelector("#valuationMetric").value;
  const valuationRecords = chartRecordsFor(state.valuations);
  const assessmentRecords = chartRecordsFor(state.assessments);
  const leftRecords = valuationRecords.length && metric !== "close" ? valuationRecords : chartRecordsFor(state.records);
  if (!valuationRecords.length && metric !== "close") metric = "close";

  if (!leftRecords.length || !assessmentRecords.length) {
    shell.classList.add("hidden");
    empty.classList.remove("hidden");
    caption.textContent = t("valuationNoCsv");
    valuationSvg.innerHTML = "";
    assessmentSvg.innerHTML = "";
    renderInvestmentAdvice(null);
    return;
  }

  shell.classList.remove("hidden");
  empty.classList.add("hidden");
  renderInvestmentAdvice(assessmentRecords[assessmentRecords.length - 1]);
  renderSingleAxisChart(valuationSvg, leftRecords, metric, "#1f7a8c");
  renderSingleAxisChart(assessmentSvg, assessmentRecords, "extra_investment_score", "#7a4f01");
  document.querySelector("#valuationChartTitle").textContent = metricLabel(metric);
  document.querySelector("#valuationChartCaption").textContent = `${leftRecords.length} ${t("recordsCount")}`;
  document.querySelector("#assessmentChartCaption").textContent = `${assessmentRecords.length} ${t("recordsCount")}`;
  caption.textContent = t("assessmentNote");
}

function updateMetricOptions() {
  const select = document.querySelector("#valuationMetric");
  const hasValuation = state.valuations.length > 0;
  ["earnings_yield", "pe_ttm", "pb"].forEach((value) => {
    const option = select.querySelector(`option[value="${value}"]`);
    if (option) option.disabled = !hasValuation;
  });
  if (!hasValuation && select.value !== "close") {
    select.value = "close";
  }
  if (hasValuation && select.value === "close") {
    select.value = "earnings_yield";
  }
}

function renderInvestmentAdvice(latestAssessment) {
  const box = document.querySelector("#investmentAdvice");
  const score = latestAssessment ? Number(latestAssessment.extra_investment_score) : NaN;
  let level = "low";
  let text = t("adviceUnavailable");
  let scoreText = "-";

  if (!Number.isNaN(score)) {
    scoreText = formatNumber(score);
    if (score >= 70) {
      level = "high";
      text = t("adviceHigh");
    } else if (score >= 40) {
      level = "medium";
      text = t("adviceMedium");
    } else {
      level = "low";
      text = t("adviceLow");
    }
  }

  const confidence = latestAssessment?.confidence === "valuation_supported" ? t("confidenceValuation") : t("confidencePriceOnly");
  const method = latestAssessment?.method || "-";
  const breakdown = latestAssessment ? [
    latestAssessment.valuation_score !== null && latestAssessment.valuation_score !== undefined ? `${t("valuationScore")} ${formatNumber(latestAssessment.valuation_score)}` : null,
    `${t("priceScore")} ${formatNumber(latestAssessment.price_score)}`,
    `${t("drawdownScore")} ${formatNumber(latestAssessment.drawdown_score)}`,
    `${t("trendScore")} ${formatNumber(latestAssessment.trend_score)}`,
  ].filter(Boolean).join(" · ") : "-";
  box.className = `advice-box ${level}`;
  box.innerHTML = `
    <strong>${t("adviceTitle")}: ${scoreText}/100</strong>
    <p>${text}</p>
    <p>${t("scoreBreakdown")}: ${breakdown}</p>
    <p>${confidence} · ${t("method")}: ${method}</p>
  `;
}

function chartRecordsFor(records) {
  const limit = Number(document.querySelector("#rangeSelect").value);
  if (!limit) return records;
  return records.slice(-limit);
}

function renderTable() {
  const body = document.querySelector("#recordsBody");
  body.innerHTML = state.records.slice(-15).reverse().map((row) => `
    <tr>
      <td>${row.date}</td>
      <td>${formatNumber(row.open)}</td>
      <td>${formatNumber(row.high)}</td>
      <td>${formatNumber(row.low)}</td>
      <td>${formatNumber(row.close)}</td>
      <td>${formatNumber(row.volume)}</td>
    </tr>
  `).join("");
}

async function selectIndex(slug) {
  state.selectedSlug = slug;
  renderIndexList();
  const data = await fetchJson(`/api/index/${slug}`);
  const valuationData = await fetchJson(`/api/valuation/${slug}`);
  const assessmentData = await fetchJson(`/api/assessment/${slug}`);
  state.currentIndex = data.index;
  state.records = data.records;
  state.valuations = valuationData.records;
  state.assessments = assessmentData.records;
  updateMetricOptions();
  renderSummary(data.index);
  renderValuationChart();
  renderTable();
}

function rerenderCurrentView() {
  applyTranslations();
  renderIndexList();
  if (state.currentIndex) renderSummary(state.currentIndex);
  renderValuationChart();
  renderTable();
}

async function init() {
  applyTranslations();
  const data = await fetchJson("/api/indices");
  state.indices = data.indices;
  state.selectedSlug = state.indices[0]?.slug;
  renderIndexList();
  if (state.selectedSlug) await selectIndex(state.selectedSlug);
}

document.querySelector("#rangeSelect").addEventListener("change", renderValuationChart);
document.querySelector("#valuationMetric").addEventListener("change", renderValuationChart);
document.querySelector("#reloadButton").addEventListener("click", () => selectIndex(state.selectedSlug));
document.querySelector("#languageButton").addEventListener("click", () => {
  state.lang = state.lang === "en" ? "zh" : "en";
  localStorage.setItem("marketDashboardLanguage", state.lang);
  rerenderCurrentView();
});
window.addEventListener("resize", () => {
  renderValuationChart();
});

init().catch((error) => {
  document.querySelector("#selectedName").textContent = t("unableToLoad");
  document.querySelector("#selectedMeta").textContent = error.message;
});
