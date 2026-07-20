/* ============================================================
   Minor Planet Names – app.js
   ============================================================ */

const state = {
  queryTerms: [],
  queryMode: "and",
  queryTarget: "both",
  orbits: [],
  citationCategories: [],
  personRoles: [],
  genders: [],
  discoverers: [],
  observatories: [],
  flags: [],
  sort: "alpha",
  direction: "asc",
  limit: 30,
  offset: 0,
  total: 0,
  selectedPermid: null,
  allOrbitFacets: [],
  allCitationFacets: [],
  allPersonRoleFacets: [],
  allGenderFacets: [],
  allDiscovererFacets: [],
  allObservatoryFacets: [],
  allFlagFacets: [],
};

// Mapping from stateKey -> label shown in tags
const FILTER_META = {
  orbits:            { label: "軌道",       kind: "orbit" },
  citationCategories:{ label: "命名",       kind: "citation" },
  personRoles:       { label: "人物ロール", kind: "person_role" },
  genders:           { label: "性別",       kind: "gender" },
  discoverers:       { label: "発見者",     kind: "discoverer" },
  observatories:     { label: "観測所",     kind: "observatory" },
  flags:             { label: "フラグ",     kind: "flag" },
};

const els = {
  query:               qs("#query"),
  queryMode:           qs("#queryMode"),
  queryTarget:         qs("#queryTarget"),
  clearQuery:          qs("#clearQuery"),
  filterMenuBtn:       qs("#filterMenuBtn"),
  filterBadgeCount:    qs("#filterBadgeCount"),
  clearAllFiltersBtn:  qs("#clearAllFiltersBtn"),
  queryHelp:           qs("#queryHelp"),
  activeFilterTags:    qs("#activeFilterTags"),
  orbitFilters:        qs("#orbitFilters"),
  citationFilters:     qs("#citationFilters"),
  personRoleFilters:   qs("#personRoleFilters"),
  genderFilters:       qs("#genderFilters"),
  discovererFilters:   qs("#discovererFilters"),
  observatoryFilters:  qs("#observatoryFilters"),
  flagFilters:         qs("#flagFilters"),
  resetFilters:        qs("#resetFilters"),
  filterModal:         qs("#filterModal"),
  filterModalClose:    qs("#filterModalClose"),
  filterModalApply:    qs("#filterModalApply"),
  sortField:           qs("#sortField"),
  sortDirection:       qs("#sortDirection"),
  results:             qs("#results"),
  loadingOverlay:      qs("#loadingOverlay"),
  resultSummary:       qs("#resultSummary"),
  totalObjects:        qs("#totalObjects"),
  totalResults:        qs("#totalResults"),
  datasetMeta:         qs("#datasetMeta"),
  firstPage:           qs("#firstPage"),
  prevPage:            qs("#prevPage"),
  pageDropdownBtn:     qs("#pageDropdownBtn"),
  pageDropdown:        qs("#pageDropdown"),
  pageLabel:           qs("#pageLabel"),
  nextPage:            qs("#nextPage"),
  lastPage:            qs("#lastPage"),
  wordCloud:           qs("#wordCloud"),
  wordCount:           qs("#wordCount"),
  genderStats:         qs("#genderStats"),
  genderStatsTotal:    qs("#genderStatsTotal"),
  genderStatsBar:      qs("#genderStatsBar"),
  genderStatsLegend:   qs("#genderStatsLegend"),
  detailBody:          qs("#detailBody"),
  sidePanel:           qs("#sidePanel"),
  closeSidePanel:      qs("#closeSidePanel"),
  tabDetail:           qs("#tabDetail"),
  tabWordcloud:        qs("#tabWordcloud"),
  sideTabDetail:       qs("#sideTabDetail"),
  sideTabWordcloud:    qs("#sideTabWordcloud"),
  mobileDetailOverlay: qs("#mobileDetailOverlay"),
  searchScrollContainer: qs("#searchScrollContainer"),
  searchControlsRow:   qs("#searchControlsRow"),
  langSwitch:          qs("#langSwitch"),
};

let searchTimer = null;
const AUTO_SEARCH_DEBOUNCE_MS = 450;

/* ============================================================
   INIT
   ============================================================ */
async function init() {
  await initI18n();
  els.langSwitch.value = i18next.language.startsWith('ja') ? 'ja' : 'en';
  bindEvents();
  initMobileTabs();
  updateSearchScrollShadows();
  updateQueryHelp();
  await loadStats();
  await refresh();
}

/* ============================================================
   EVENTS
   ============================================================ */
function bindEvents() {
  els.langSwitch.addEventListener("change", (e) => {
    const lang = e.target.value;
    i18next.changeLanguage(lang).then(() => {
      updateTranslations();
      renderActiveFilterTags();
      refresh(); // 再描画が必要な要素（件数等）を更新するため
    });
  });

  // Search terms: Enter adds the current input as a committed keyword.
  els.query.addEventListener("input", () => {
    updateClearQueryVisibility();
    scheduleAutoSearchIfNeeded();
  });
  els.query.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(searchTimer);
    addQueryTerm(els.query.value);
  });

  els.clearQuery.addEventListener("click", () => {
    clearTimeout(searchTimer);
    els.query.value = "";
    state.queryTerms = [];
    state.offset = 0;
    updateClearQueryVisibility();
    renderActiveFilterTags();
    refresh();
  });

  els.queryMode.addEventListener("change", () => {
    state.queryMode = els.queryMode.value === "or" ? "or" : "and";
    state.offset = 0;
    renderActiveFilterTags();
    refresh();
  });

  els.queryTarget.addEventListener("change", () => {
    const value = els.queryTarget.value;
    state.queryTarget = value === "name" || value === "citation" ? value : "both";
    state.offset = 0;
    refresh();
  });

  // Sort
  els.sortField.addEventListener("change", () => {
    state.sort = els.sortField.value;
    state.offset = 0;
    refresh();
  });
  els.sortDirection.addEventListener("change", () => {
    state.direction = els.sortDirection.value;
    state.offset = 0;
    refresh();
  });

  // Pager
  els.firstPage.addEventListener("click", () => {
    state.offset = 0;
    refresh();
  });
  els.prevPage.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    refresh();
  });
  els.nextPage.addEventListener("click", () => {
    if (state.offset + state.limit < state.total) {
      state.offset += state.limit;
      refresh();
    }
  });
  els.lastPage.addEventListener("click", () => {
    const pages = Math.max(1, Math.ceil(state.total / state.limit));
    state.offset = (pages - 1) * state.limit;
    refresh();
  });

  // Page selection dropdown toggle
  els.pageDropdownBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const show = els.pageDropdown.hidden;
    if (show) {
      openPageDropdown();
    } else {
      els.pageDropdown.hidden = true;
      els.pageDropdownBtn.setAttribute("aria-expanded", "false");
    }
  });

  // Document click to close dropdown
  document.addEventListener("click", (e) => {
    if (!els.pageDropdown.hidden && !els.pageDropdown.contains(e.target) && e.target !== els.pageDropdownBtn) {
      els.pageDropdown.hidden = true;
      els.pageDropdownBtn.setAttribute("aria-expanded", "false");
    }
  });

  // Filter modal open/close
  els.filterMenuBtn.addEventListener("click", openModal);
  els.filterModalClose.addEventListener("click", closeModal);
  els.filterModalApply.addEventListener("click", () => {
    closeModal();
    state.offset = 0;
    refresh();
  });
  els.filterModal.addEventListener("click", (e) => {
    if (e.target === els.filterModal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.filterModal.hidden) closeModal();
  });

  // Reset
  els.resetFilters.addEventListener("click", resetAllConditions);
  els.clearAllFiltersBtn.addEventListener("click", resetAllConditions);

  // Mobile side panel: close button & overlay = minimize
  els.closeSidePanel.addEventListener("click", (e) => {
    e.stopPropagation(); // ヘッダータップへのバブル伝播を防ぐ
    closeMobileDetail();
  });
  els.mobileDetailOverlay.addEventListener("click", closeMobileDetail);

  // Mobile tabs: タブクリックで展開 + タブ切り替え
  els.tabDetail.addEventListener("click", (e) => {
    e.stopPropagation();
    switchMobileTab("detail");
    if (isMobile()) openMobileDetail();
  });
  els.tabWordcloud.addEventListener("click", (e) => {
    e.stopPropagation();
    switchMobileTab("wordcloud");
    if (isMobile()) openMobileDetail();
  });

  // ヘッダーバー全体をタップで展開（閉じるボタンおよびタブボタンを除く）
  els.sidePanel.querySelector(".side-panel-mobile-header").addEventListener("click", () => {
    if (isMobile() && !els.sidePanel.classList.contains("is-open")) openMobileDetail();
  });

  // Escape closes mobile panel too
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && els.sidePanel.classList.contains("is-open")) closeMobileDetail();
  });

  // Search row scroll shadows
  els.searchControlsRow.addEventListener("scroll", updateSearchScrollShadows);
  window.addEventListener("resize", updateSearchScrollShadows);
}

function resetAllConditions() {
  clearTimeout(searchTimer);
  state.queryTerms = [];
  state.queryMode = "and";
  state.queryTarget = "both";
  state.orbits = [];
  state.citationCategories = [];
  state.personRoles = [];
  state.genders = [];
  state.discoverers = [];
  state.observatories = [];
  state.flags = [];
  state.sort = "alpha";
  state.direction = "asc";
  state.offset = 0;
  els.query.value = "";
  els.queryMode.value = state.queryMode;
  els.queryTarget.value = state.queryTarget;
  updateClearQueryVisibility();
  els.sortField.value = state.sort;
  els.sortDirection.value = state.direction;
  closeModal();
  refresh();
}

function hasAnyActiveCondition() {
  return state.queryTerms.length > 0
    || state.orbits.length > 0
    || state.citationCategories.length > 0
    || state.personRoles.length > 0
    || state.genders.length > 0
    || state.discoverers.length > 0
    || state.observatories.length > 0
    || state.flags.length > 0;
}

function openModal() {
  els.filterModal.hidden = false;
  renderFacets();
  // フィルタ内のチェックリストをトップに戻す
  document.querySelectorAll(".check-list").forEach((el) => { el.scrollTop = 0; });
  document.body.style.overflow = "hidden";
}
function closeModal() {
  els.filterModal.hidden = true;
  // モバイルでは body overflow は変更しない（ページスクロールは常時許可）
  if (window.innerWidth > 740) {
    document.body.style.overflow = "";
  }
}

/* ============================================================
   DATA LOADING
   ============================================================ */
async function loadStats() {
  const stats = await getJson("/api/stats");
  els.totalObjects.textContent = formatNumber(stats.total);
  if (stats.latest_updated_at) {
    els.datasetMeta.textContent = i18next.t("header.dataset_meta_updated", { date: stats.latest_updated_at.slice(0, 10) });
  } else {
    els.datasetMeta.textContent = i18next.t("header.dataset_meta_none");
  }
  state.allOrbitFacets        = stats.orbit_types         || [];
  state.allCitationFacets     = stats.citation_categories || [];
  state.allPersonRoleFacets   = stats.person_roles         || [];
  state.allGenderFacets       = stats.genders              || [];
  state.allDiscovererFacets   = stats.discoverers          || [];
  state.allObservatoryFacets  = stats.observatories        || [];
  state.allFlagFacets         = stats.flags               || [];
}

async function refresh() {
  const params = currentParams();
  els.loadingOverlay.hidden = false;
  try {
    const [searchData, wordData, facetData] = await Promise.all([
      getJson(`/api/search?${params.toString()}`),
      getJson(`/api/wordcloud?${params.toString()}`),
      getJson(`/api/facets?${params.toString()}`),
    ]);
    state.total = searchData.total;
    // 動的ファセットカウントを更新
    state.allOrbitFacets        = _mergeFacets(state.allOrbitFacets,        facetData.orbit_types         || []);
    state.allCitationFacets     = _mergeFacets(state.allCitationFacets,     facetData.citation_categories || []);
    state.allPersonRoleFacets   = _mergeFacets(state.allPersonRoleFacets,   facetData.person_roles         || []);
    state.allGenderFacets       = _mergeFacets(state.allGenderFacets,       facetData.genders              || []);
    state.allDiscovererFacets   = _mergeFacets(state.allDiscovererFacets,   facetData.discoverers          || []);
    state.allObservatoryFacets  = _mergeFacets(state.allObservatoryFacets,  facetData.observatories        || []);
    state.allFlagFacets         = _mergeFacets(state.allFlagFacets,         facetData.flags               || []);
    renderResults(searchData.items || []);
    renderWordCloud(wordData.words || []);
    renderGenderStats(facetData.genders || []);
    renderActiveFilterTags();
    updatePager();
    // フィルターモーダルが開いている場合はファセット表示を更新
    if (!els.filterModal.hidden) renderFacets();
    // スクロールをトップに戻す
    els.results.scrollTop = 0;
    els.wordCloud.scrollTop = 0;
  } finally {
    els.loadingOverlay.hidden = true;
  }
}

/**
 * モーダル内のチェック操作時にファセット件数だけを更新する（検索結果は変えない）。
 * state[stateKey] は呼び出し前に更新済みであること。
 */
async function refreshFacetsOnly() {
  const params = currentParams();
  try {
    const facetData = await getJson(`/api/facets?${params.toString()}`);
    state.allOrbitFacets        = _mergeFacets(state.allOrbitFacets,        facetData.orbit_types         || []);
    state.allCitationFacets     = _mergeFacets(state.allCitationFacets,     facetData.citation_categories || []);
    state.allPersonRoleFacets   = _mergeFacets(state.allPersonRoleFacets,   facetData.person_roles         || []);
    state.allGenderFacets       = _mergeFacets(state.allGenderFacets,       facetData.genders              || []);
    state.allDiscovererFacets   = _mergeFacets(state.allDiscovererFacets,   facetData.discoverers          || []);
    state.allObservatoryFacets  = _mergeFacets(state.allObservatoryFacets,  facetData.observatories        || []);
    state.allFlagFacets         = _mergeFacets(state.allFlagFacets,         facetData.flags               || []);
    renderFacets();
  } catch (e) {
    console.warn("facet refresh failed", e);
  }
}

/**
 * 全件ファセット (baseFacets) と絞り込み後ファセット (liveFacets) をマージする。
 * 絞り込み後に消えたアイテムも count=0 として残し、常に全オプションを表示する。
 */
function _mergeFacets(baseFacets, liveFacets) {
  const liveMap = new Map(liveFacets.map((f) => [f.value, f.count]));
  return baseFacets.map((f) => ({
    value: f.value,
    count: liveMap.has(f.value) ? liveMap.get(f.value) : 0,
  }));
}

function currentParams() {
  const params = new URLSearchParams();
  getSearchTermsForRequest().forEach((v) => params.append("q", v));
  params.set("q_mode", state.queryMode);
  params.set("q_target", state.queryTarget);
  state.orbits.forEach((v)            => params.append("orbit", v));
  state.citationCategories.forEach((v)=> params.append("citation_category", v));
  state.personRoles.forEach((v)        => params.append("person_role", v));
  state.genders.forEach((v)            => params.append("gender", v));
  state.discoverers.forEach((v)       => params.append("discoverer", v));
  state.observatories.forEach((v)     => params.append("observatory", v));
  state.flags.forEach((v)             => params.append("flag", v));
  params.set("sort",      state.sort);
  params.set("direction", state.direction);
  params.set("limit",     String(state.limit));
  params.set("offset",    String(state.offset));
  return params;
}

/* ============================================================
   RENDER: RESULTS
   ============================================================ */
function renderResults(items) {
  if (state.total === 0) {
    els.results.innerHTML = `<div class="empty">${i18next.t("app.result_summary_zero")}</div>`;
    els.resultSummary.textContent = i18next.t("app.result_summary_zero");
    els.pageLabel.textContent = "1 / 1";
    updatePagerButtons(1);
    return;
  }

  const start = state.offset + 1;
  const end = Math.min(state.offset + state.limit, state.total);
  els.resultSummary.textContent = i18next.t("app.result_summary", { start: formatNumber(start), end: formatNumber(end), total: formatNumber(state.total) });

  els.results.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `result-row${item.permid === state.selectedPermid ? " active" : ""}`;
    row.innerHTML = `
      <div class="row-title">
        <strong>${escapeHtml(item.name_display || item.name_ascii)}</strong>
        <span class="meta">(${escapeHtml(item.permid)})</span>
      </div>
      <div class="badges">${renderSearchBadges(item)}</div>
      ${renderDiscoveryLine(item)}
      <p class="snippet">${renderSnippet(item.citation_snippet || "Citation なし")}</p>
    `;
    row.addEventListener("click", () => loadDetail(item.permid));
    els.results.appendChild(row);
  });
}

function renderDiscoveryLine(item) {
  if (!item.discovery_site && !item.discoverer_text) return "";
  const parts = [];
  if (item.discovery_date)  parts.push(escapeHtml(item.discovery_date));
  if (item.discovery_site)  parts.push(`Obs: ${escapeHtml(item.discovery_site)}`);
  if (item.discoverer_text) parts.push(escapeHtml(item.discoverer_text));
  return `<p class="discovery-line">${parts.join(" · ")}</p>`;
}

function renderSearchBadges(item) {
  const b = [];
  if (item.orbit_type) b.push(`<span class="badge orbit">${escapeHtml(item.orbit_type)}</span>`);
  (item.citation_categories || []).forEach((c) =>
    b.push(`<span class="badge citation">${escapeHtml(c)}</span>`)
  );
  (item.person_roles || []).forEach((role) =>
    b.push(`<span class="badge citation">${escapeHtml(role)}</span>`)
  );
  if (item.gender) b.push(`<span class="badge citation">${escapeHtml(item.gender)}</span>`);
  if (item.is_neo) b.push(`<span class="badge flag">NEO</span>`);
  if (item.is_pha) b.push(`<span class="badge pha">PHA</span>`);
  return b.join("");
}

/* ============================================================
   RENDER: ACTIVE FILTER TAGS
   ============================================================ */
function renderActiveFilterTags() {
  updateQueryHelp();
  els.activeFilterTags.innerHTML = "";
  let total = 0;
  for (const value of state.queryTerms) {
    const isNegated = value.startsWith("!");
    const modeLabel = isNegated ? "NOT" : state.queryMode.toUpperCase();
    const displayValue = isNegated ? (value.slice(1).trim() || value) : value;
    total++;
    const tag = document.createElement("span");
    tag.className = `filter-tag search-tag${isNegated ? " search-tag-not" : ""}`;
    tag.innerHTML = `
      <span class="filter-tag-kind">${i18next.t("app.filter_tag_search", { mode: modeLabel })}</span>
      ${escapeHtml(displayValue)}
      <span class="filter-tag-remove" aria-label="${i18next.t("app.remove")}">✕</span>
    `;
    tag.addEventListener("click", (e) => {
      if (!e.target.classList.contains("filter-tag-remove")) {
        els.query.focus();
      }
    });
    tag.querySelector(".filter-tag-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      state.queryTerms = state.queryTerms.filter((v) => v !== value);
      state.offset = 0;
      updateClearQueryVisibility();
      refresh();
    });
    els.activeFilterTags.appendChild(tag);
  }
  for (const [stateKey, meta] of Object.entries(FILTER_META)) {
    for (const value of state[stateKey]) {
      total++;
      const tag = document.createElement("span");
      tag.className = "filter-tag";
      tag.innerHTML = `
        <span class="filter-tag-kind">${escapeHtml(meta.label)}</span>
        ${escapeHtml(value)}
        <span class="filter-tag-remove" aria-label="${i18next.t("app.remove")}">✕</span>
      `;
      // Click body → open modal for editing
      tag.addEventListener("click", (e) => {
        if (!e.target.classList.contains("filter-tag-remove")) {
          openModal();
        }
      });
      // Click × → remove the single value
      tag.querySelector(".filter-tag-remove").addEventListener("click", (e) => {
        e.stopPropagation();
        state[stateKey] = state[stateKey].filter((v) => v !== value);
        state.offset = 0;
        refresh();
      });
      els.activeFilterTags.appendChild(tag);
    }
  }
  // Badge count on filter button
  if (total > 0) {
    els.filterBadgeCount.textContent = String(total);
    els.filterBadgeCount.hidden = false;
  } else {
    els.filterBadgeCount.hidden = true;
  }
  els.clearAllFiltersBtn.hidden = !hasAnyActiveCondition();
}

/* ============================================================
   RENDER: FILTER MODAL CHECKBOXES
   ============================================================ */
function renderFacets() {
  renderCheckboxGroup(els.orbitFilters,       state.allOrbitFacets,       state.orbits,             "orbits");
  renderCheckboxGroup(els.citationFilters,    state.allCitationFacets,    state.citationCategories, "citationCategories");
  renderCheckboxGroup(els.personRoleFilters,  state.allPersonRoleFacets,  state.personRoles,        "personRoles");
  renderCheckboxGroup(els.genderFilters,      state.allGenderFacets,      state.genders,            "genders");
  renderCheckboxGroup(els.discovererFilters,  state.allDiscovererFacets,  state.discoverers,        "discoverers");
  renderCheckboxGroup(els.observatoryFilters, state.allObservatoryFacets, state.observatories,      "observatories");
  renderCheckboxGroup(els.flagFilters,        state.allFlagFacets,        state.flags,              "flags");
}

function renderCheckboxGroup(container, values, selected, stateKey) {
  container.innerHTML = "";
  if (!values.length) {
    container.innerHTML = `<div class="empty">${i18next.t("app.no_options")}</div>`;
    return;
  }
  values.forEach((item) => {
    const id = `chk-${stateKey}-${slug(item.value)}`;
    const isChecked = selected.includes(item.value);
    const isZero    = item.count === 0 && !isChecked;
    const label = document.createElement("label");
    label.className = `check-option${isZero ? " is-zero" : ""}`;
    label.htmlFor = id;
    label.innerHTML = `
      <input id="${id}" type="checkbox" value="${escapeHtml(item.value)}" ${isChecked ? "checked" : ""}${isZero ? " disabled" : ""}>
      <span class="label">${escapeHtml(item.value)}</span>
      <span class="count">${formatNumber(item.count)}</span>
    `;
    if (!isZero) {
      label.querySelector("input").addEventListener("change", (e) => {
        const checked = e.target.checked;
        const value   = e.target.value;
        const cur     = new Set(state[stateKey]);
        if (checked) cur.add(value); else cur.delete(value);
        state[stateKey] = Array.from(cur);
        // タグを即時更新し、ファセット件数もリアルタイムで更新する
        renderActiveFilterTags();
        refreshFacetsOnly();
      });
    }
    container.appendChild(label);
  });
}

function addQueryTerm(rawValue) {
  clearTimeout(searchTimer);
  const term = normalizeQueryInput(rawValue);
  if (!term) {
    updateClearQueryVisibility();
    return;
  }
  if (!state.queryTerms.includes(term)) {
    state.queryTerms = [...state.queryTerms, term];
    state.offset = 0;
  }
  els.query.value = "";
  updateClearQueryVisibility();
  refresh();
}

function updateClearQueryVisibility() {
  els.clearQuery.hidden = els.query.value.trim().length === 0 && state.queryTerms.length === 0;
}

function normalizeQueryInput(rawValue) {
  const cleaned = String(rawValue).replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  if (!cleaned.startsWith("!")) return cleaned;
  const negatedBody = cleaned.replace(/^!+/, "").trim();
  return negatedBody ? `!${negatedBody}` : "";
}

function getSearchTermsForRequest() {
  if (state.queryTerms.length > 0) return state.queryTerms;
  const pending = normalizeQueryInput(els.query.value);
  return pending ? [pending] : [];
}

function scheduleAutoSearchIfNeeded() {
  clearTimeout(searchTimer);
  if (state.queryTerms.length > 0) return;
  const pending = normalizeQueryInput(els.query.value);
  if (!pending) {
    state.offset = 0;
    refresh();
    return;
  }
  searchTimer = setTimeout(() => {
    state.offset = 0;
    refresh();
  }, AUTO_SEARCH_DEBOUNCE_MS);
}

function updateQueryHelp() {
  // queryHelpはindex.html側でdata-i18n属性で処理するためここでの更新は不要
  els.queryHelp.hidden = state.queryTerms.length > 0;
}

/* ============================================================
   RENDER: WORD CLOUD
   ============================================================ */
function renderWordCloud(words) {
  els.wordCloud.innerHTML = "";
  els.wordCount.textContent = `${formatNumber(words.length)}語`;
  if (!words.length) {
    els.wordCloud.innerHTML = `<div class="empty">キーワードなし</div>`;
    return;
  }
  const max = Math.max(...words.map((w) => w.count));
  words.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "keyword-row";
    row.title = `${item.word}: ${item.count}件`;
    row.innerHTML = `
      <span class="keyword-rank">${index + 1}</span>
      <span class="keyword-word">${escapeHtml(item.word)}</span>
      <span class="keyword-meter"><span style="width:${Math.max(6, Math.round((item.count / max) * 100))}%"></span></span>
      <span class="keyword-count">${formatNumber(item.count)}</span>
    `;
    els.wordCloud.appendChild(row);
  });
}

const GENDER_ORDER = ["Female", "Male", "Multiple/Mixed", "Unknown", "Non-person"];

function renderGenderStats(facets) {
  const counts = new Map(facets.map((facet) => [facet.value, facet.count]));
  const ordered = [
    ...GENDER_ORDER.filter((value) => counts.has(value)),
    ...facets.map((facet) => facet.value).filter((value) => !GENDER_ORDER.includes(value)),
  ].map((value) => ({ value, count: counts.get(value) || 0 })).filter((item) => item.count > 0);
  const total = ordered.reduce((sum, item) => sum + item.count, 0);

  els.genderStats.hidden = total === 0;
  if (!total) return;

  els.genderStatsTotal.textContent = `${formatNumber(total)}件`;
  els.genderStatsBar.innerHTML = ordered.map((item) => {
    const percentage = (item.count / total) * 100;
    const label = `${item.value}: ${formatNumber(item.count)} (${percentage.toFixed(1)}%)`;
    return `<span class="gender-segment gender-segment--${slug(item.value)}" style="width:${percentage}%" title="${escapeHtml(label)}"></span>`;
  }).join("");
  els.genderStatsBar.setAttribute("aria-label", `${i18next.t("side.gender_stats")}: ${ordered.map((item) => `${item.value} ${formatNumber(item.count)}`).join(", ")}`);
  els.genderStatsLegend.innerHTML = ordered.map((item) => `
    <span class="gender-legend-item">
      <i class="gender-legend-swatch gender-segment--${slug(item.value)}"></i>
      <span>${escapeHtml(item.value)}</span>
      <strong>${formatNumber(item.count)}</strong>
    </span>
  `).join("");
}

/* ============================================================
   RENDER: DETAIL
   ============================================================ */
async function loadDetail(permid) {
  state.selectedPermid = permid;
  document.querySelectorAll(".result-row").forEach((r) => r.classList.remove("active"));
  const detail  = await getJson(`/api/objects/${encodeURIComponent(permid)}`);
  const active  = document.querySelector(`.result-row[data-permid="${CSS.escape(permid)}"]`);
  if (active) active.classList.add("active");

  const catBadges = (detail.categories || []).map(renderDetailBadge).join("");
  const facetBadges = (detail.citation_facets || []).map(renderDetailFacetBadge).join("");
  const roleFacets = (detail.citation_facets || []).filter((facet) => facet.kind === "person_role");
  const genderFacet = (detail.citation_facets || []).find((facet) => facet.kind === "entity_gender");
  const publicationSection = renderPublicationSection(detail);
  const personFacetSection = renderPersonFacetSection(roleFacets, genderFacet);

  els.detailBody.innerHTML = `
    <div class="row-title">
      <strong>${escapeHtml(detail.name_display || detail.name_ascii)}</strong>
      <span class="meta">${escapeHtml(detail.iau_designation || `(${detail.permid})`)}</span>
    </div>
    <div class="badges" style="margin-bottom:8px">${catBadges || `<span class="badge">Uncategorized</span>`}${facetBadges}</div>
    <div class="detail-grid">
      <div><span>Semimajor axis</span>${formatValue(detail.semimajor_axis, " AU")}</div>
      <div><span>Eccentricity</span>${formatValue(detail.eccentricity)}</div>
      <div><span>Inclination</span>${formatValue(detail.inclination, "°")}</div>
      <div><span>H (abs.mag)</span>${formatValue(detail.absolute_magnitude_h)}</div>
      <div><span>Discovery</span>${formatValue(detail.discovery_date)}</div>
      <div><span>Observatory</span>${formatValue(detail.discovery_site)}</div>
    </div>
    <p class="discovery-line">${escapeHtml(detail.discoverer_text ? `Discoverer: ${detail.discoverer_text}` : "Discoverer: unknown")}</p>
    ${publicationSection}
    ${personFacetSection}
    <div class="ext-links">
      <a class="ext-link ext-link--mpc" href="https://www.minorplanetcenter.net/db_search/show_object?object_id=${encodeURIComponent(detail.permid)}" target="_blank" rel="noopener noreferrer">
        MPC &rarr;
      </a>
      <a class="ext-link ext-link--jpl" href="https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=${encodeURIComponent(detail.permid)}" target="_blank" rel="noopener noreferrer">
        JPL SBDB &rarr;
      </a>
    </div>
  `;
  // 詳細パネルのスクロールをトップに戻す
  els.detailBody.scrollTop = 0;

  // モバイル: 詳細タブにフォーカスしてパネルを開く
  if (isMobile()) {
    switchMobileTab("detail");
    openMobileDetail();
  }
}

function renderPublicationSection(detail) {
  const hasPublication = detail.naming_published_year || detail.naming_reference || detail.naming_source_url;
  if (!hasPublication) return "";
  const source = detail.naming_source_url
    ? `<a href="${escapeHtml(detail.naming_source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(detail.naming_source || i18next.t("detail.source"))} ↗</a>`
    : escapeHtml(detail.naming_source || "—");
  return `
    <section class="detail-section">
      <h3>${i18next.t("detail.naming_publication")}</h3>
      <dl class="detail-facts">
        <div><dt>${i18next.t("detail.publication_date")}</dt><dd>${escapeHtml(detail.naming_published_year || "—")}</dd></div>
        <div><dt>${i18next.t("detail.reference")}</dt><dd>${escapeHtml(detail.naming_reference || "—")}</dd></div>
        <div><dt>${i18next.t("detail.source")}</dt><dd>${source}</dd></div>
      </dl>
    </section>
  `;
}

function renderPersonFacetSection(roleFacets, genderFacet) {
  if (!roleFacets.length && !genderFacet) return "";
  const values = [
    ...roleFacets.map((facet) => ({ label: i18next.t("detail.roles"), facet })),
    ...(genderFacet ? [{ label: i18next.t("detail.gender"), facet: genderFacet }] : []),
  ];
  return `
    <section class="detail-section">
      <h3>${i18next.t("detail.person_facets")}</h3>
      <div class="detail-facet-list">
        ${values.map(({ label, facet }) => `
          <div class="detail-facet-row">
            <span class="detail-facet-label">${escapeHtml(label)}</span>
            <span class="badge citation">${escapeHtml(facet.value)}</span>
            ${facet.evidence_text ? `<p>${i18next.t("detail.evidence")}: ${escapeHtml(facet.evidence_text)}</p>` : ""}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderDetailBadge(category) {
  if (category.kind === "orbit")    return `<span class="badge orbit">Orbit: ${escapeHtml(category.value)}</span>`;
  if (category.kind === "citation") return `<span class="badge citation">${escapeHtml(category.value)}</span>`;
  if (category.kind === "flag")     return `<span class="badge ${category.value === "PHA" ? "pha" : "flag"}">${escapeHtml(category.value)}</span>`;
  return `<span class="badge">${escapeHtml(category.value)}</span>`;
}

function renderDetailFacetBadge(facet) {
  const prefix = facet.kind === "person_role" ? "Role" : "Gender";
  const title = [facet.evidence_text, facet.source, facet.confidence != null ? `confidence ${facet.confidence}` : ""]
    .filter(Boolean)
    .join(" · ");
  return `<span class="badge citation"${title ? ` title="${escapeHtml(title)}"` : ""}>${prefix}: ${escapeHtml(facet.value)}</span>`;
}

/* ============================================================
   PAGER
   ============================================================ */
function updatePager() {
  const page  = Math.floor(state.offset / state.limit) + 1;
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  els.pageLabel.textContent    = `${page} / ${pages}`;
  els.firstPage.disabled       = state.offset === 0;
  els.prevPage.disabled        = state.offset === 0;
  els.nextPage.disabled        = state.offset + state.limit >= state.total;
  els.lastPage.disabled        = state.offset + state.limit >= state.total;

  els.pageDropdown.hidden = true;
  els.pageDropdownBtn.setAttribute("aria-expanded", "false");
}

function openPageDropdown() {
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  const currentPage = Math.floor(state.offset / state.limit) + 1;
  els.pageDropdown.innerHTML = "";

  // 1. Create input row
  const searchRow = document.createElement("div");
  searchRow.className = "page-dropdown-search";
  
  const input = document.createElement("input");
  input.type = "number";
  input.min = "1";
  input.max = String(pages);
  input.value = String(currentPage);
  input.placeholder = "ページ";
  
  const goBtn = document.createElement("button");
  goBtn.type = "button";
  goBtn.textContent = "移動";
  
  const jumpToPage = (val) => {
    let p = parseInt(val, 10);
    if (!isNaN(p)) {
      p = Math.max(1, Math.min(pages, p));
      state.offset = (p - 1) * state.limit;
      els.pageDropdown.hidden = true;
      els.pageDropdownBtn.setAttribute("aria-expanded", "false");
      refresh();
    }
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      jumpToPage(input.value);
    }
  });
  goBtn.addEventListener("click", () => {
    jumpToPage(input.value);
  });

  searchRow.appendChild(input);
  searchRow.appendChild(goBtn);
  els.pageDropdown.appendChild(searchRow);

  // 2. Create list wrap
  const listWrap = document.createElement("div");
  listWrap.className = "page-dropdown-list";

  for (let i = 1; i <= pages; i++) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `page-dropdown-item${i === currentPage ? " active" : ""}`;
    btn.role = "option";
    btn.ariaSelected = i === currentPage ? "true" : "false";
    btn.textContent = `${i} ページ`;
    btn.addEventListener("click", () => {
      state.offset = (i - 1) * state.limit;
      els.pageDropdown.hidden = true;
      els.pageDropdownBtn.setAttribute("aria-expanded", "false");
      refresh();
    });
    listWrap.appendChild(btn);
  }
  els.pageDropdown.appendChild(listWrap);

  els.pageDropdown.hidden = false;
  els.pageDropdownBtn.setAttribute("aria-expanded", "true");

  input.focus();
  input.select();

  const activeItem = listWrap.querySelector(".page-dropdown-item.active");
  if (activeItem) {
    listWrap.scrollTop = activeItem.offsetTop - (listWrap.clientHeight / 2) + (activeItem.clientHeight / 2);
  }
}

/* ============================================================
   UTILITIES
   ============================================================ */
function qs(sel) { return document.querySelector(sel); }

function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "value";
}

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function formatNumber(v) {
  return new Intl.NumberFormat("en-US").format(v || 0);
}

function formatValue(v, suffix = "") {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return `${Number(v.toFixed(5))}${suffix}`;
  return `${escapeHtml(String(v))}${suffix}`;
}

function escapeHtml(v) {
  return String(v)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * Like escapeHtml, but converts sentinel bytes (\x00…\x01) inserted by the
 * Python snippet builder into <mark> highlight spans.
 */
function renderSnippet(v) {
  const escaped = escapeHtml(String(v));
  // \x00 and \x01 survived JSON serialisation unchanged.
  return escaped
    .replaceAll("\x00", '<mark class="hl">')
    .replaceAll("\x01", "</mark>");
}

/* ============================================================
   MOBILE DETAIL PANEL
   ============================================================ */

/** 初期タブ状態を設定（常にdetailタブから始める） */
function initMobileTabs() {
  switchMobileTab("detail");
}

/** 現在モバイルレイアウトか判定 */
function isMobile() {
  return window.matchMedia("(max-width: 740px)").matches;
}

/** モバイル用詳細パネルを開く */
function openMobileDetail() {
  els.sidePanel.classList.add("is-open");
  els.mobileDetailOverlay.hidden = false;
  document.body.style.overflow = "hidden";
}

/** モバイル用詳細パネルを最小化（タブバーのみ表示）に戻す */
function closeMobileDetail() {
  els.sidePanel.classList.remove("is-open");
  els.mobileDetailOverlay.hidden = true;
  document.body.style.overflow = "";
  // is-openを外すだけで transform: translateY(calc(100% - 44px)) に戻る
}

/**
 * モバイルタブを切り替える
 * @param {"detail"|"wordcloud"} tab
 */
function switchMobileTab(tab) {
  const isDetail = tab === "detail";
  // タブボタンのアクティブ状態
  els.tabDetail.classList.toggle("active", isDetail);
  els.tabWordcloud.classList.toggle("active", !isDetail);
  els.tabDetail.setAttribute("aria-selected", isDetail ? "true" : "false");
  els.tabWordcloud.setAttribute("aria-selected", isDetail ? "false" : "true");
  // パネルの表示切り替え
  els.sideTabDetail.classList.toggle("tab-active", isDetail);
  els.sideTabWordcloud.classList.toggle("tab-active", !isDetail);
}

/** 検索コントロールの横スクロールシャドウを更新 */
function updateSearchScrollShadows() {
  const row = els.searchControlsRow;
  if (!row) return;
  // 横スクロールの余地があるか
  const hasScroll = row.scrollWidth > row.clientWidth;
  
  if (!hasScroll) {
    els.searchScrollContainer.classList.remove("can-scroll-left", "can-scroll-right");
    return;
  }
  
  const scrollLeft = row.scrollLeft;
  const maxScroll = row.scrollWidth - row.clientWidth;
  
  // 1px程度の誤差を許容
  const canScrollLeft = scrollLeft > 1;
  const canScrollRight = scrollLeft < maxScroll - 1;
  
  els.searchScrollContainer.classList.toggle("can-scroll-left", canScrollLeft);
  els.searchScrollContainer.classList.toggle("can-scroll-right", canScrollRight);
}

/* ============================================================
   BOOT
   ============================================================ */
init().catch((err) => {
  console.error(err);
  els.results.innerHTML = `<div class="empty">${i18next && i18next.isInitialized ? i18next.t("app.error_loading") : "Failed to load data."}</div>`;
});
