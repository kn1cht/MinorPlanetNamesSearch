const translations = {
  en: {
    translation: {
      "header.title": "Minor Planet Names",
      "header.named_objects": "Named Objects",
      "header.dataset_meta_loading": "Loading...",
      "header.dataset_meta_updated": "Updated {{date}}",
      "header.dataset_meta_none": "No dataset loaded",
      
      "search.placeholder": "Search...",
      "search.mode_and": "AND",
      "search.mode_or": "OR",
      "search.target_both": "Name + Citation",
      "search.target_name": "Name only",
      "search.target_citation": "Citation only",
      "search.filter_btn": "Filters",
      "search.clear_all": "Clear Filters",
      "search.help": "Press Enter to add keywords, use !prefix to exclude.",
      
      "sort.alpha": "Name",
      "sort.number": "Number",
      "sort.absolute_magnitude": "Abs. Magnitude",
      "sort.semimajor_axis": "Semi-major Axis",
      "sort.eccentricity": "Eccentricity",
      "sort.inclination": "Inclination",
      "sort.asc": "↑ Asc",
      "sort.desc": "↓ Desc",
      
      "side.tab_detail": "Detail",
      "side.tab_wordcloud": "Word Cloud",
      "side.detail_empty": "Select an object from the list.",
      "side.detail_title": "Detail",
      "side.wordcloud_title": "Word Cloud",
      "side.gender_stats": "Gender distribution",

      "detail.naming_publication": "Naming publication",
      "detail.publication_date": "Publication date",
      "detail.reference": "Reference",
      "detail.source": "Source",
      "detail.person_facets": "Person facets",
      "detail.roles": "Role",
      "detail.gender": "Gender",
      "detail.evidence": "Evidence",
      
      "modal.title": "Filter Conditions",
      "modal.orbit": "Orbit Type",
      "modal.citation": "Citation Category",
      "modal.person_role": "Person Role",
      "modal.gender": "Gender",
      "modal.discoverer": "Discoverer",
      "modal.observatory": "Observatory",
      "modal.flag": "Flags",
      "modal.reset": "Reset All",
      "modal.apply": "Apply",
      
      "app.error_loading": "Failed to load data.",
      "app.result_summary": "Showing {{start}} - {{end}} of {{total}} results",
      "app.result_summary_zero": "No results found",
      "app.filter_tag_search": "Search ({{mode}})",
      "app.remove": "Remove",
      "app.no_options": "No options available"
    }
  },
  ja: {
    translation: {
      "header.title": "Minor Planet Names",
      "header.named_objects": "Named Objects",
      "header.dataset_meta_loading": "読み込み中...",
      "header.dataset_meta_updated": "Updated {{date}}",
      "header.dataset_meta_none": "データセットなし",
      
      "search.placeholder": "検索",
      "search.mode_and": "AND",
      "search.mode_or": "OR",
      "search.target_both": "名前+Citation",
      "search.target_name": "名前のみ",
      "search.target_citation": "Citationのみ",
      "search.filter_btn": "絞り込み",
      "search.clear_all": "条件クリア",
      "search.help": "Enterで複数キーワードを追加、!キーワードで除外検索できます。",
      
      "sort.alpha": "名前順",
      "sort.number": "番号順",
      "sort.absolute_magnitude": "等級順",
      "sort.semimajor_axis": "軌道長半径順",
      "sort.eccentricity": "離心率順",
      "sort.inclination": "傾斜角順",
      "sort.asc": "↑ 昇順",
      "sort.desc": "↓ 降順",
      
      "side.tab_detail": "詳細",
      "side.tab_wordcloud": "キーワード頻度",
      "side.detail_empty": "リストから天体を選択してください。",
      "side.detail_title": "詳細",
      "side.wordcloud_title": "キーワード頻度",
      "side.gender_stats": "性別統計",

      "detail.naming_publication": "命名公表情報",
      "detail.publication_date": "公表日",
      "detail.reference": "参照",
      "detail.source": "情報源",
      "detail.person_facets": "人物ファセット",
      "detail.roles": "ロール",
      "detail.gender": "性別",
      "detail.evidence": "根拠",
      
      "modal.title": "絞り込み条件",
      "modal.orbit": "軌道分類",
      "modal.citation": "命名カテゴリ",
      "modal.person_role": "人物ロール",
      "modal.gender": "性別",
      "modal.discoverer": "発見者",
      "modal.observatory": "観測所",
      "modal.flag": "フラグ",
      "modal.reset": "すべてリセット",
      "modal.apply": "適用",
      
      "app.error_loading": "データの読み込みに失敗しました。",
      "app.result_summary": "{{total}} 件中 {{start}} - {{end}} 件を表示",
      "app.result_summary_zero": "結果がありません",
      "app.filter_tag_search": "検索({{mode}})",
      "app.remove": "解除",
      "app.no_options": "オプションなし"
    }
  }
};

async function initI18n() {
  const userLang = navigator.language.startsWith("ja") ? "ja" : "en";
  await i18next.init({
    lng: userLang,
    fallbackLng: "en",
    resources: translations
  });
  updateTranslations();
}

function updateTranslations() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (el.tagName === "INPUT" && el.hasAttribute("placeholder")) {
      el.placeholder = i18next.t(key);
    } else {
      // SVGなどが子にある場合はテキストノードだけ置換するか、まるごと置換するか注意
      // data-i18n属性を持つ要素はなるべく中にテキストしか持たない構造にする
      el.textContent = i18next.t(key);
    }
  });
}
