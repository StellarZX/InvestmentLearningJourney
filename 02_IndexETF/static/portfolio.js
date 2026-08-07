"use strict";

const state = {
  lang: "zh",
  portfolio: null,
};

const translations = {
  zh: {
    portfolioTitle: "持仓记录",
    portfolioSubtitle: "当前持仓与定投记录（数据库保存）。",
    portfolioEyebrow: "持仓与记录",
    navIndices: "指数看板",
    navDca: "定投决策",
    navPortfolio: "持仓记录",
    navHoldings: "持仓应急",
    portfolioSourceNote: "记录保存在本地数据库 02_IndexETF/data/market.db。",
    addRecord: "添加记录",
    addRecordTitle: "添加定投记录",
    fFund: "基金",
    fDate: "日期",
    fPosition: "持仓金额（最新）",
    fCost: "成本（累计）",
    fNote: "备注",
    formSave: "保存",
    formCancel: "取消",
    currentHoldings: "当前持仓",
    recordHistory: "记录历史",
    hFund2: "基金",
    dcaCode: "代码",
    dcaQuota: "目标",
    curPct: "当前占比",
    curPosition: "持仓",
    curCost: "成本",
    curReturn: "收益率",
    holdingsCount: "项持仓",
    shares: "份",
    unableToLoad: "无法加载数据",
    saved: "记录已保存",
  },
};

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function t(key) {
  return translations[state.lang][key] || key;
}

function applyTranslations() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("portfolioTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
}

function positionText(item) {
  if (item.code === "SXR8") return `${fmt.format(item.position)} ${t("shares")}`;
  return `${item.currency === "EUR" ? "€" : "¥"}${fmt.format(item.position)}`;
}

function render(payload) {
  state.portfolio = payload;
  document.querySelector("#portfolioError").classList.add("hidden");
  document.querySelector("#portfolioTitle").textContent = t("portfolioTitle");
  document.querySelector("#portfolioCaption").textContent = `${payload.holdings.length} ${t("holdingsCount")}`;

  document.querySelector("#holdingsBody").innerHTML = payload.holdings.map((h) => `
    <tr>
      <td>${h.fund}</td>
      <td>${h.code}</td>
      <td>${h.target}</td>
      <td>${h.current_pct}</td>
      <td>${positionText(h)}</td>
      <td>${h.currency === "EUR" ? "€" : "¥"}${fmt.format(h.cost)}</td>
      <td>${h.return_pct}</td>
    </tr>`).join("");

  document.querySelector("#recordsBody").innerHTML = payload.records.map((r) => `
    <tr>
      <td>${r.date}</td>
      <td>${r.fund}</td>
      <td>${r.code}</td>
      <td>${r.code === "SXR8" ? `${fmt.format(r.position)} ${t("shares")}` : `${r.currency === "EUR" ? "€" : "¥"}${fmt.format(r.position)}`}</td>
      <td>${r.currency === "EUR" ? "€" : "¥"}${fmt.format(r.cost)}</td>
      <td>${r.note || ""}</td>
    </tr>`).join("");

  const select = document.querySelector("#formFund");
  select.innerHTML = payload.funds
    .map((f) => `<option value="${f.code}">${f.code} ${f.name}</option>`)
    .join("");
  if (!document.querySelector("#formDate").value) {
    document.querySelector("#formDate").value = new Date().toISOString().slice(0, 10);
  }
}

async function loadPortfolio() {
  try {
    const response = await fetch("/api/portfolio");
    if (!response.ok) throw new Error(`Request failed: /api/portfolio`);
    render(await response.json());
  } catch (error) {
    const box = document.querySelector("#portfolioError");
    box.textContent = `${t("unableToLoad")}: ${error.message}`;
    box.classList.remove("hidden");
  }
}

function showForm(show) {
  document.querySelector("#recordForm").classList.toggle("hidden", !show);
  document.querySelector("#formError").textContent = "";
}

document.querySelector("#addRecordButton").addEventListener("click", () => showForm(true));
document.querySelector("#formCancel").addEventListener("click", () => showForm(false));

document.querySelector("#formSave").addEventListener("click", async () => {
  const body = {
    code: document.querySelector("#formFund").value,
    date: document.querySelector("#formDate").value,
    position: document.querySelector("#formPosition").value,
    cost: document.querySelector("#formCost").value,
    note: document.querySelector("#formNote").value,
  };
  try {
    const response = await fetch("/api/records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    showForm(false);
    document.querySelector("#formPosition").value = "";
    document.querySelector("#formCost").value = "";
    document.querySelector("#formNote").value = "";
    render(data.portfolio);
  } catch (error) {
    document.querySelector("#formError").textContent = `${t("unableToLoad")}: ${error.message}`;
  }
});

applyTranslations();
loadPortfolio();
