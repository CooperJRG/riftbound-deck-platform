(function () {
  const ASSET_BASE = "assets/skeuo";
  const CARD_BACK_DEFAULT = `${ASSET_BASE}/card-backs/card_back_clean_768x1024.png`;
  const CARD_BACK_VARIANTS = Array.from({ length: 16 }).map((_, idx) => {
    const id = String(idx + 1).padStart(2, "0");
    return `${ASSET_BASE}/card-backs/variants/card_back_variant_${id}.png`;
  });

  const DOMAIN_COLOR_CLASS = {
    Calm: "domain-calm",
    Chaos: "domain-chaos",
    Body: "domain-body",
    Fury: "domain-fury",
    Mind: "domain-mind",
    Order: "domain-order"
  };

  const CANON_SET_ORDER = ["Origins", "Proving Grounds", "Spiritforged"];
  const CANON_RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Showcase"];

  const state = {
    collection: {},
    collectionOwnedByKey: {},
    collectionAvailableByKey: {},
    collectionInUseByKey: {},
    library: [],
    metaDecks: [],
    cards: [],
    cardsByTitle: {},
    cardsByKey: {},
    deck: {
      name: "Untitled Deck",
      source: "builder",
      format: "constructed",
      legendTitle: "",
      chosenChampionTitle: "",
      main: {},
      runes: {},
      battlefields: ["", "", ""],
      sideboard: {}
    },
    eligibility: {
      legendTitle: "",
      legendDomains: [],
      legends: [],
      champions: [],
      battlefields: [],
      runes: [],
      recommendedRunes: {},
      mainDeckSize: 40,
      runeDeckSize: 12,
      battlefieldCount: 3,
      mainCopyLimit: 3,
      allowedMainCardTypes: ["Unit", "Gear", "Spell"]
    },
    picker: {
      kind: "",
      battlefieldIndex: 0
    },
    ui: {
      expandedDeckSection: "",
      workspaceTab: "deck",
      replacementCardTitle: "",
      collectionEditMode: false,
      collectionFiltersOpen: false,
      collectionSearch: "",
      collectionFilters: {
        set: "",
        rarity: "",
        domain: "",
        role: ""
      }
    },
    analysis: {
      active: false,
      summary: null,
      replacementByCard: {},
      mainMissingByTitle: {},
      mainOwnedCopies: 0
    },
    lastValidation: null,
    validateTimer: null
  };

  async function api(path, options) {
    const init = options || {};
    const res = await fetch(path, {
      headers: init.body ? { "Content-Type": "application/json" } : undefined,
      ...init,
      body: init.body ? JSON.stringify(init.body) : undefined
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = payload && payload.detail ? payload.detail : res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function escAttr(text) {
    return esc(text).replace(/"/g, "&quot;");
  }

  function stripStarterSuffix(text) {
    return String(text == null ? "" : text)
      .replace(/[\u2013\u2014]/g, "-")
      .replace(/\s*[-,]\s*starter\s*$/i, "")
      .trim();
  }

  function normalizeCardKey(text) {
    const raw = stripStarterSuffix(String(text == null ? "" : text)).trim();
    if (!raw) return "";
    return raw
      .replace(/[&][#A-Za-z0-9]+[;]/g, "")
      .replace(/[\u2018\u2019\u2032\uFF07`´]/g, "'")
      .toLowerCase()
      .replace(/\s*-\s*/g, " ")
      .replace(/\s*,\s*/g, " ")
      .replace(/[^a-z0-9]+/g, "");
  }

  function hashString(text) {
    let hash = 2166136261;
    const raw = String(text == null ? "" : text);
    for (let i = 0; i < raw.length; i += 1) {
      hash ^= raw.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function cardBackFor(title) {
    if (!CARD_BACK_VARIANTS.length) return CARD_BACK_DEFAULT;
    const idx = hashString(title) % CARD_BACK_VARIANTS.length;
    return CARD_BACK_VARIANTS[idx] || CARD_BACK_DEFAULT;
  }

  function cardTiltFor(title) {
    const raw = hashString(`tilt:${title}`);
    const steps = (raw % 9) - 4;
    return `${(steps * 0.18).toFixed(2)}deg`;
  }

  function lookupCard(title) {
    const clean = stripStarterSuffix(String(title || "").trim());
    if (!clean) return null;
    if (state.cardsByTitle[clean]) return state.cardsByTitle[clean];
    const key = normalizeCardKey(clean);
    if (!key) return null;
    return state.cardsByKey[key] || null;
  }

  function canonicalTitle(title) {
    const clean = stripStarterSuffix(String(title || "").trim());
    if (!clean) return "";
    const info = lookupCard(clean);
    return (info && info.title) || clean;
  }

  function initials(title) {
    const words = String(title || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!words.length) return "??";
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
  }

  function cardMetaLine(cardInfo) {
    if (!cardInfo) return "";
    const kind = [cardInfo.cardType, cardInfo.superType].filter(Boolean).join(" / ");
    const domains = Array.isArray(cardInfo.domains) ? cardInfo.domains.join(", ") : "";
    const parts = [];
    if (kind) parts.push(kind);
    if (domains) parts.push(domains);
    return parts.join(" | ");
  }

  function cardStatsLine(cardInfo) {
    if (!cardInfo) return "";
    const stats = [];
    if (cardInfo.cost != null && cardInfo.cost !== "") stats.push(`Cost ${cardInfo.cost}`);
    if (cardInfo.might != null && cardInfo.might !== "") stats.push(`Might ${cardInfo.might}`);
    return stats.join(" | ");
  }

  function rarityRank(rarity) {
    const raw = String(rarity || "").trim().toLowerCase();
    if (!raw) return 0;
    if (raw.includes("showcase")) return 5;
    if (raw.includes("epic")) return 4;
    if (raw.includes("rare")) return 3;
    if (raw.includes("uncommon")) return 2;
    if (raw.includes("common")) return 1;
    return 0;
  }

  function normalizeRarityLabel(rarity) {
    const raw = String(rarity || "").trim().toLowerCase();
    if (!raw) return "";
    if (raw.includes("showcase")) return "Showcase";
    if (raw.includes("epic")) return "Epic";
    if (raw.includes("rare")) return "Rare";
    if (raw.includes("uncommon")) return "Uncommon";
    if (raw.includes("common")) return "Common";
    return String(rarity || "").trim();
  }

  function normalizeSetLabel(setName) {
    const raw = String(setName || "").trim().replace(/\s+/g, " ");
    if (!raw) return "";
    const lower = raw.toLowerCase();
    if (lower.includes("origins") || /\bogn\b/.test(lower)) return "Origins";
    if (lower.includes("proving grounds") || /\bogs\b/.test(lower)) return "Proving Grounds";
    if (lower.includes("spiritforged") || /\bsfd\b/.test(lower)) return "Spiritforged";
    const stripped = raw.replace(/^[A-Za-z]{3}\s*-\s*/u, "").trim();
    return stripped || raw;
  }

  function setOrderRank(setLabel) {
    const clean = normalizeSetLabel(setLabel);
    const idx = CANON_SET_ORDER.indexOf(clean);
    return idx >= 0 ? idx : CANON_SET_ORDER.length + 100;
  }

  function parseCardNumberIndex(rawCardNumber) {
    const raw = String(rawCardNumber || "").trim();
    if (!raw) return 999999;
    const slash = raw.match(/(\d+)\s*\/\s*\d+/u);
    if (slash && slash[1]) return Number.parseInt(slash[1], 10) || 999999;
    const first = raw.match(/(\d+)/u);
    if (first && first[1]) return Number.parseInt(first[1], 10) || 999999;
    return 999999;
  }

  function compareCardsBySetAndNumber(leftCard, leftTitle, rightCard, rightTitle) {
    const leftSet = normalizeSetLabel((leftCard && leftCard.set) || "");
    const rightSet = normalizeSetLabel((rightCard && rightCard.set) || "");
    const leftSetRank = setOrderRank(leftSet);
    const rightSetRank = setOrderRank(rightSet);
    if (leftSetRank !== rightSetRank) return leftSetRank - rightSetRank;
    if (leftSet !== rightSet) return leftSet.localeCompare(rightSet);

    const leftNo = parseCardNumberIndex(leftCard && leftCard.cardNumber);
    const rightNo = parseCardNumberIndex(rightCard && rightCard.cardNumber);
    if (leftNo !== rightNo) return leftNo - rightNo;

    const lTitle = String(leftTitle || (leftCard && leftCard.title) || "");
    const rTitle = String(rightTitle || (rightCard && rightCard.title) || "");
    return lTitle.localeCompare(rTitle);
  }

  function compareTitlesByCatalogOrder(leftTitle, rightTitle) {
    const leftCard = lookupCard(leftTitle);
    const rightCard = lookupCard(rightTitle);
    return compareCardsBySetAndNumber(leftCard, leftTitle, rightCard, rightTitle);
  }

  function isFoilRarity(rarity) {
    return rarityRank(rarity) >= 4;
  }

  function legendChampionTagSet() {
    const legend = lookupCard(state.deck.legendTitle || "");
    const tags = legend && Array.isArray(legend.championTags) ? legend.championTags : [];
    return new Set(tags.map((tag) => String(tag || "").trim()).filter(Boolean));
  }

  function cardChampionTagSet(card) {
    const tags = card && Array.isArray(card.championTags) ? card.championTags : [];
    return new Set(tags.map((tag) => String(tag || "").trim()).filter(Boolean));
  }

  function isSignatureCard(card) {
    return String((card && card.superType) || "").trim() === "Signature";
  }

  function mainCopyCapForTitle(title) {
    const card = lookupCard(title);
    const base = Math.max(1, Number(state.eligibility.mainCopyLimit || 3) || 3);
    if (card && card.isUnique) return 1;
    return base;
  }

  function coerceCountMap(raw) {
    const out = {};
    const src = raw && typeof raw === "object" ? raw : {};
    Object.keys(src).forEach((title) => {
      const clean = canonicalTitle(title);
      const qty = Math.max(0, Number(src[title] || 0) || 0);
      if (clean && qty > 0) out[clean] = (out[clean] || 0) + qty;
    });
    return out;
  }

  function normalizeDeckPayload(raw) {
    const src = raw && typeof raw === "object" ? raw : {};
    const battlefields = Array.isArray(src.battlefields)
      ? src.battlefields.map((v) => canonicalTitle(v)).filter(Boolean)
      : [];
    while (battlefields.length < 3) battlefields.push("");
    return {
      name: String(src.name || "Untitled Deck").trim() || "Untitled Deck",
      source: String(src.source || "builder").trim() || "builder",
      format: String(src.format || "constructed").trim() || "constructed",
      legendTitle: canonicalTitle(src.legendTitle || src.legend_title || ""),
      chosenChampionTitle: canonicalTitle(src.chosenChampionTitle || src.chosen_champion_title || ""),
      main: coerceCountMap(src.main),
      runes: coerceCountMap(src.runes),
      battlefields: battlefields.slice(0, 3),
      sideboard: coerceCountMap(src.sideboard)
    };
  }

  function currentDeckFromForm() {
    return normalizeDeckPayload(state.deck);
  }

  function mainTotal() {
    return Object.values(state.deck.main || {}).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
  }

  function runeTotal() {
    return Object.values(state.deck.runes || {}).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
  }

  function collectionKeyMap(cards) {
    const map = {};
    const src = cards && typeof cards === "object" ? cards : {};
    Object.keys(src).forEach((title) => {
      const qty = Math.max(0, Number(src[title] || 0) || 0);
      if (qty <= 0) return;
      const key = normalizeCardKey(title);
      if (!key) return;
      map[key] = (map[key] || 0) + qty;
    });
    return map;
  }

  function collectionOwnedCopies(title) {
    const key = normalizeCardKey(title);
    if (!key) return 0;
    return Math.max(0, Number(state.collectionOwnedByKey[key] || 0) || 0);
  }

  function collectionAvailableCopies(title) {
    const key = normalizeCardKey(title);
    if (!key) return 0;
    return Math.max(0, Number(state.collectionAvailableByKey[key] || 0) || 0);
  }

  function collectionInUseCopies(title) {
    const key = normalizeCardKey(title);
    if (!key) return 0;
    return Math.max(0, Number(state.collectionInUseByKey[key] || 0) || 0);
  }

  function summarizeMainDeckCollectionCoverage() {
    const missingByTitle = {};
    let ownedTotal = 0;
    Object.entries(state.deck.main || {}).forEach(([rawTitle, rawQty]) => {
      const title = canonicalTitle(rawTitle);
      const required = Math.max(0, Number(rawQty) || 0);
      if (!title || required <= 0) return;
      const owned = collectionAvailableCopies(title);
      const ownedForDeck = Math.min(required, owned);
      const missing = Math.max(0, required - ownedForDeck);
      ownedTotal += ownedForDeck;
      if (missing > 0) {
        missingByTitle[title] = {
          card: title,
          required,
          owned: ownedForDeck,
          missing
        };
      }
    });
    return { missingByTitle, ownedTotal };
  }

  function collectionMergedOwnedMap() {
    const merged = {};
    const src = state.collection && typeof state.collection === "object" ? state.collection : {};
    Object.keys(src).forEach((rawTitle) => {
      const qty = Math.max(0, Number(src[rawTitle] || 0) || 0);
      if (qty <= 0) return;
      const title = canonicalTitle(rawTitle) || stripStarterSuffix(String(rawTitle || "").trim());
      if (!title) return;
      merged[title] = (merged[title] || 0) + qty;
    });
    return merged;
  }

  function cardMatchesCollectionRole(card, role) {
    const target = String(role || "").trim();
    if (!target) return true;
    if (!card) return false;
    const cardType = String(card.cardType || "").trim();
    const superType = String(card.superType || "").trim();
    if (target === "Champion" || target === "Legend" || target === "Signature") {
      return superType === target || cardType === target;
    }
    return cardType === target;
  }

  function cardMatchesCollectionFilters(row) {
    const needle = normalizeCardKey((state.ui && state.ui.collectionSearch) || "");
    const filters = (state.ui && state.ui.collectionFilters) || {};
    const title = String((row && row.title) || "");
    const card = row && row.card ? row.card : null;
    if (needle && !normalizeCardKey(title).includes(needle)) return false;
    if (filters.set) {
      const setName = normalizeSetLabel((card && card.set) || "");
      if (setName !== filters.set) return false;
    }
    if (filters.rarity) {
      const rarity = normalizeRarityLabel((card && card.rarity) || "");
      if (rarity !== filters.rarity) return false;
    }
    if (filters.domain) {
      const domains = Array.isArray(card && card.domains) ? card.domains.map((v) => String(v || "").trim()) : [];
      if (!domains.includes(filters.domain)) return false;
    }
    if (!cardMatchesCollectionRole(card, filters.role)) return false;
    return true;
  }

  function collectionBrowserRows() {
    const editMode = Boolean(state.ui && state.ui.collectionEditMode);
    const rows = [];
    if (editMode) {
      (state.cards || []).forEach((card) => {
        if (!card || !card.title) return;
        rows.push({
          title: card.title,
          qty: collectionOwnedCopies(card.title),
          card
        });
      });
    } else {
      const owned = collectionMergedOwnedMap();
      Object.keys(owned).forEach((title) => {
        rows.push({
          title,
          qty: Math.max(0, Number(owned[title] || 0) || 0),
          card: lookupCard(title)
        });
      });
    }
    return rows
      .filter((row) => cardMatchesCollectionFilters(row))
      .sort((a, b) => compareCardsBySetAndNumber(a.card, a.title, b.card, b.title));
  }

  function collectionFilterValues() {
    const sets = new Set();
    const rarities = new Set();
    const domains = new Set();
    (state.cards || []).forEach((card) => {
      if (!card) return;
      const setName = normalizeSetLabel(card.set || "");
      const rarity = normalizeRarityLabel(card.rarity || "");
      if (setName) sets.add(setName);
      if (rarity) rarities.add(rarity);
      (Array.isArray(card.domains) ? card.domains : []).forEach((domain) => {
        const clean = String(domain || "").trim();
        if (clean) domains.add(clean);
      });
    });
    return {
      sets: Array.from(sets).sort((a, b) => {
        const da = setOrderRank(a) - setOrderRank(b);
        if (da !== 0) return da;
        return String(a).localeCompare(String(b));
      }),
      rarities: Array.from(rarities).sort((a, b) => {
        const raRaw = rarityRank(a);
        const rbRaw = rarityRank(b);
        const ra = raRaw > 0 ? raRaw : 999;
        const rb = rbRaw > 0 ? rbRaw : 999;
        if (ra !== rb) return ra - rb;
        const ia = CANON_RARITY_ORDER.indexOf(String(a));
        const ib = CANON_RARITY_ORDER.indexOf(String(b));
        if (ia !== ib && ia >= 0 && ib >= 0) return ia - ib;
        return String(a).localeCompare(String(b));
      }),
      domains: Array.from(domains).sort((a, b) => a.localeCompare(b))
    };
  }

  function fillFilterSelect(selectId, label, values, currentValue) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const selected = String(currentValue || "");
    const options = [`<option value="">${esc(label)}</option>`]
      .concat((values || []).map((value) => `<option value="${escAttr(value)}">${esc(value)}</option>`))
      .join("");
    el.innerHTML = options;
    el.value = selected;
  }

  function renderCollectionControls() {
    const filterPanel = document.getElementById("collection-filter-panel");
    if (filterPanel) filterPanel.hidden = !Boolean(state.ui && state.ui.collectionFiltersOpen);

    const editBtn = document.getElementById("collection-edit-toggle-btn");
    if (editBtn) {
      const isEdit = Boolean(state.ui && state.ui.collectionEditMode);
      editBtn.textContent = isEdit ? "Done" : "Edit";
      editBtn.setAttribute("aria-pressed", isEdit ? "true" : "false");
    }

    const filterBtn = document.getElementById("collection-filter-toggle-btn");
    if (filterBtn) {
      const open = Boolean(state.ui && state.ui.collectionFiltersOpen);
      filterBtn.textContent = open ? "Hide Filters" : "Filters";
      filterBtn.setAttribute("aria-pressed", open ? "true" : "false");
    }

    const search = document.getElementById("collection-search-input");
    if (search && search.value !== state.ui.collectionSearch) {
      search.value = state.ui.collectionSearch || "";
    }

    const filterLists = collectionFilterValues();
    const f = state.ui.collectionFilters || {};
    fillFilterSelect("collection-filter-set", "All Sets", filterLists.sets, f.set);
    fillFilterSelect("collection-filter-rarity", "All Rarities", filterLists.rarities, f.rarity);
    fillFilterSelect("collection-filter-domain", "All Colors", filterLists.domains, f.domain);
    fillFilterSelect(
      "collection-filter-role",
      "All Roles",
      ["Champion", "Legend", "Signature", "Unit", "Spell", "Gear", "Rune", "Battlefield"],
      f.role
    );
  }

  async function setCollectionQuantity(title, quantity) {
    const clean = canonicalTitle(title) || String(title || "").trim();
    if (!clean) return;
    const nextQty = Math.max(0, Number(quantity || 0) || 0);
    const payload = await api("/api/collection/item", {
      method: "PUT",
      body: { card: clean, quantity: nextQty }
    });
    renderCollection(payload);
  }

  async function adjustCollectionQuantity(title, delta) {
    if (!title || !delta) return;
    const current = collectionOwnedCopies(title);
    const next = Math.max(0, current + (Number(delta) || 0));
    if (next === current) return;
    await setCollectionQuantity(title, next);
  }

  function collectionSnapshotFromState() {
    const cards = state.collection && typeof state.collection === "object" ? state.collection : {};
    const availableCards = {};
    const inUseCards = {};
    Object.keys(cards).forEach((title) => {
      const owned = Math.max(0, Number(cards[title] || 0) || 0);
      if (owned <= 0) return;
      const inUse = collectionInUseCopies(title);
      const available = Math.max(0, owned - inUse);
      if (inUse > 0) inUseCards[title] = inUse;
      if (available > 0) availableCards[title] = available;
    });
    return {
      cards,
      in_use_cards: inUseCards,
      available_cards: availableCards,
      total_unique_cards: Object.keys(cards).length,
      total_copies: Object.values(cards).reduce((sum, qty) => sum + (Math.max(0, Number(qty) || 0)), 0),
      total_in_use_copies: Object.values(inUseCards).reduce((sum, qty) => sum + (Math.max(0, Number(qty) || 0)), 0),
      total_available_copies: Object.values(availableCards).reduce((sum, qty) => sum + (Math.max(0, Number(qty) || 0)), 0)
    };
  }

  function rerenderCollectionFromState() {
    renderCollection(collectionSnapshotFromState(), { uiOnly: true });
  }

  function applyAnalysisSnapshot(payload) {
    const analysis = (payload && payload.analysis) || {};
    const replacementByCard = {};
    const replacementRows = Array.isArray(analysis.replacement_suggestions) ? analysis.replacement_suggestions : [];
    replacementRows.forEach((row) => {
      const key = canonicalTitle((row && row.card) || "");
      if (!key) return;
      const options = Array.isArray(row.options) ? row.options : [];
      replacementByCard[key] = options
        .map((opt) => {
          const optTitle = canonicalTitle((opt && opt.card) || "");
          if (!optTitle) return null;
          return {
            card: optTitle,
            owned: Math.max(0, Number(opt.owned || 0) || 0),
            available: Math.max(0, Number(opt.available || 0) || 0),
            score: Number(opt.score || 0) || 0
          };
        })
        .filter(Boolean);
    });

    const missingLookup = {};
    const missingRows = Array.isArray(analysis.missing_cards) ? analysis.missing_cards : [];
    missingRows.forEach((row) => {
      const key = canonicalTitle((row && row.card) || "");
      if (!key) return;
      missingLookup[key] = {
        required: Math.max(0, Number(row.required || 0) || 0),
        owned: Math.max(0, Number(row.owned || 0) || 0),
        missing: Math.max(0, Number(row.missing || 0) || 0)
      };
    });

    const mainMissingByTitle = {};
    let mainOwnedCopies = 0;
    Object.entries(state.deck.main || {}).forEach(([rawTitle, rawQty]) => {
      const title = canonicalTitle(rawTitle);
      const required = Math.max(0, Number(rawQty) || 0);
      if (!title || required <= 0) return;
      const row = missingLookup[title];
      const missing = Math.min(required, Math.max(0, Number(row && row.missing) || 0));
      const owned = Math.max(0, required - missing);
      mainOwnedCopies += owned;
      if (missing > 0) {
        mainMissingByTitle[title] = { card: title, required, owned, missing };
      }
    });

    state.analysis.active = true;
    state.analysis.summary = analysis;
    state.analysis.replacementByCard = replacementByCard;
    state.analysis.mainMissingByTitle = mainMissingByTitle;
    state.analysis.mainOwnedCopies = mainOwnedCopies;
  }

  function refreshActiveAnalysisView() {
    if (!state.analysis.active) return;
    const coverage = summarizeMainDeckCollectionCoverage();
    state.analysis.mainMissingByTitle = coverage.missingByTitle;
    state.analysis.mainOwnedCopies = coverage.ownedTotal;
    const open = canonicalTitle(state.ui.replacementCardTitle || "");
    if (open && !state.analysis.mainMissingByTitle[open]) {
      closeReplacementModal();
    }
  }

  function setStatus(text, error) {
    const el = document.getElementById("app-status");
    if (!el) return;
    el.textContent = text;
    el.style.color = error ? "#ffd6d8" : "#d9ffeb";
  }

  function applyWorkspaceTab() {
    const active = String((state.ui && state.ui.workspaceTab) || "deck").trim() === "collection" ? "collection" : "deck";
    state.ui.workspaceTab = active;

    const collectionPanel = document.getElementById("collection-panel");
    const deckPanel = document.getElementById("deck-panel");
    if (collectionPanel) {
      const on = active === "collection";
      collectionPanel.classList.toggle("is-active", on);
      collectionPanel.hidden = !on;
    }
    if (deckPanel) {
      const on = active === "deck";
      deckPanel.classList.toggle("is-active", on);
      deckPanel.hidden = !on;
    }

    Array.from(document.querySelectorAll("[data-workspace-tab]")).forEach((btn) => {
      const target = String(btn.getAttribute("data-workspace-tab") || "").trim();
      const on = target === active;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.setAttribute("tabindex", on ? "0" : "-1");
    });
  }

  function setWorkspaceTab(nextTab) {
    state.ui.workspaceTab = String(nextTab || "").trim() === "collection" ? "collection" : "deck";
    applyWorkspaceTab();
  }

  function applyDeckSectionFocus() {
    const worktable = document.querySelector(".deck-worktable");
    if (!worktable) return;
    const section = String((state.ui && state.ui.expandedDeckSection) || "").trim();
    const valid = new Set(["battlefields", "main-deck", "library"]);
    const active = valid.has(section) ? section : "";

    worktable.classList.remove("is-focus-battlefields", "is-focus-main-deck", "is-focus-library");
    if (active) {
      worktable.classList.add(`is-focus-${active}`);
    }

    Array.from(worktable.querySelectorAll(".section-expandable[data-worktable-section]")).forEach((row) => {
      const rowSection = String(row.getAttribute("data-worktable-section") || "").trim();
      row.classList.toggle("is-expanded", Boolean(active) && rowSection === active);
      row.classList.toggle("is-minimized", Boolean(active) && rowSection !== active);
    });

    Array.from(document.querySelectorAll("[data-section-expand]")).forEach((btn) => {
      const target = String(btn.getAttribute("data-section-expand") || "").trim();
      const isActive = Boolean(active) && target === active;
      btn.textContent = isActive ? "Restore" : "Expand";
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function toggleDeckSectionFocus(section) {
    const target = String(section || "").trim();
    if (!target) return;
    if (state.ui.expandedDeckSection === target) state.ui.expandedDeckSection = "";
    else state.ui.expandedDeckSection = target;
    applyDeckSectionFocus();
    renderMainDeckList();
  }

  function setLegalityIndicator(validation) {
    const wrap = document.getElementById("deck-legality-wrap");
    const led = document.getElementById("deck-legality-led");
    if (!wrap || !led) return;
    if (!validation) {
      led.style.background = "radial-gradient(circle at 30% 30%, #d6d6d6 0%, #6f6f6f 76%)";
      led.style.boxShadow = "0 0 6px rgba(220, 220, 220, 0.35)";
      wrap.removeAttribute("title");
      return;
    }
    if (validation.is_valid) {
      led.style.background = "radial-gradient(circle at 30% 30%, #96f5b8 0%, #2f7f45 76%)";
      led.style.boxShadow = "0 0 8px rgba(123, 249, 160, 0.62)";
      wrap.removeAttribute("title");
      return;
    }
    const issues = Array.isArray(validation.issues) ? validation.issues : [];
    const tip = issues
      .slice(0, 8)
      .map((issue) => `[${issue.code}] ${issue.message}`)
      .join("\n");
    led.style.background = "radial-gradient(circle at 30% 30%, #ffadad 0%, #9d2b2f 76%)";
    led.style.boxShadow = "0 0 8px rgba(255, 109, 109, 0.6)";
    if (tip) wrap.title = tip;
    else wrap.removeAttribute("title");
  }

  function tileHtml(opts) {
    const title = String(opts.title || "Unknown");
    const imageUrl = String(opts.imageUrl || "");
    const subtitle = String(opts.subtitle || "");
    const badge = String(opts.badge || "");
    const badgeClass = String(opts.badgeClass || "");
    const extraAttrs = String(opts.extraAttrs || "").trim();
    const meta = String(opts.meta || "");
    const stats = String(opts.stats || "");
    const actions = String(opts.actions || "");
    const extraClass = String(opts.extraClass || "");
    const artOverlay = String(opts.artOverlay || "");
    const providedRarity = String(opts.rarity || "").trim();
    const shelfOnly = Boolean(opts.shelfOnly);
    const info = lookupCard(title);
    const rarity = providedRarity || String((info && info.rarity) || "").trim();
    const foil = Boolean(imageUrl) && isFoilRarity(rarity) && !Boolean(opts.disableFoil);
    const fallback = initials(title);
    const backImage = cardBackFor(title);
    const resolvedImage = imageUrl || backImage || CARD_BACK_DEFAULT;
    const hasCatalogImage = Boolean(imageUrl);
    const art =
      `<img src="${escAttr(resolvedImage)}"` +
      ` alt="${escAttr(title)} artwork"` +
      ` loading="lazy"` +
      ` data-fallback-src="${escAttr(backImage || CARD_BACK_DEFAULT)}"` +
      ` class="${hasCatalogImage ? "" : "is-fallback"}"` +
      " />";
    const sheenOverlay = `<div class="card-sheen" aria-hidden="true"></div>`;
    const foilOverlay = foil ? `<div class="foil-holo" aria-hidden="true"></div>` : "";
    const bodyContent =
      shelfOnly
        ? (actions ? `<div class="card-actions">${actions}</div>` : "")
        : `<div class="card-title" title="${escAttr(title)}">${esc(title)}</div>` +
          (subtitle ? `<div class="card-subtitle">${esc(subtitle)}</div>` : "") +
          (actions ? `<div class="card-actions">${actions}</div>` : "");
    return (
      `<article class="card-tile ${esc(extraClass)}${shelfOnly ? " shelf-card" : ""}${foil ? " is-foil" : ""}"` +
      ` style="--card-tilt:${escAttr(cardTiltFor(title))};"` +
      ` data-preview-title="${escAttr(title)}"` +
      ` data-preview-image="${escAttr(resolvedImage)}"` +
      ` data-preview-meta="${escAttr(meta)}"` +
      ` data-preview-stats="${escAttr(stats)}"` +
      ` data-preview-fallback="${escAttr(fallback)}"` +
      ` data-preview-back="${escAttr(backImage || CARD_BACK_DEFAULT)}"` +
      ` data-rarity="${escAttr(rarity)}"` +
      (extraAttrs ? ` ${extraAttrs}` : "") +
      `>` +
      `<div class="card-art">` +
      sheenOverlay +
      foilOverlay +
      (shelfOnly ? "" : badge ? `<div class="card-pill ${esc(badgeClass)}">${esc(badge)}</div>` : "") +
      artOverlay +
      art +
      `</div>` +
      (bodyContent ? `<div class="card-body">${bodyContent}</div>` : "") +
      `</article>`
    );
  }

  function skeletonTiles(count) {
    const n = Math.max(1, Number(count) || 1);
    return Array.from({ length: n })
      .map(() => `<article class="card-tile skeleton"><div class="card-art"></div><div class="card-body"></div></article>`)
      .join("");
  }

  function validationFieldLabel(field) {
    const raw = String(field || "").trim();
    if (!raw) return "General";
    const key = raw.split(".")[0];
    const known = {
      legendTitle: "Legend",
      chosenChampionTitle: "Chosen Champion",
      main: "Main Deck",
      runes: "Runes",
      battlefields: "Battlefields",
      sideboard: "Sideboard"
    }[key];
    if (known) return known;
    return key
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^./, (ch) => ch.toUpperCase());
  }

  function formatRuleRefs(issue) {
    const refs = Array.isArray(issue && issue.rule_refs) ? issue.rule_refs : [];
    const clean = refs.map((row) => String(row || "").trim()).filter(Boolean);
    if (!clean.length) return "";
    return clean.map((row) => `<span class="validation-ref-chip">${esc(row)}</span>`).join("");
  }

  function renderValidation(validation) {
    const root = document.getElementById("deck-validation");
    if (!root) return;
    if (!validation) {
      root.innerHTML =
        `<div class="validation-panel is-empty">` +
        `<div class="validation-headline">Validation updates as you edit the deck.</div>` +
        `</div>`;
      return;
    }
    const issues = Array.isArray(validation.issues) ? validation.issues : [];
    const summary = String(validation.summary || "").trim() || (validation.is_valid ? "Deck is valid." : "Deck has issues.");
    const uniqueCodes = new Set(issues.map((issue) => String((issue && issue.code) || "").trim()).filter(Boolean));
    const uniqueRefs = new Set();
    issues.forEach((issue) => {
      const refs = Array.isArray(issue && issue.rule_refs) ? issue.rule_refs : [];
      refs.forEach((ref) => {
        const value = String(ref || "").trim();
        if (value) uniqueRefs.add(value);
      });
    });

    const head =
      `<div class="validation-head">` +
      `<span class="validation-state-pill ${validation.is_valid ? "is-legal" : "is-illegal"}">${validation.is_valid ? "Legal" : "Illegal"}</span>` +
      `<div class="validation-summary-text">${esc(summary)}</div>` +
      `</div>`;
    const metrics =
      `<div class="validation-metrics">` +
      `<div class="validation-metric"><span>Issues</span><strong>${esc(issues.length)}</strong></div>` +
      `<div class="validation-metric"><span>Rule Codes</span><strong>${esc(uniqueCodes.size)}</strong></div>` +
      `<div class="validation-metric"><span>Rule Refs</span><strong>${esc(uniqueRefs.size)}</strong></div>` +
      `</div>`;

    if (validation.is_valid) {
      root.innerHTML =
        `<div class="validation-panel is-valid">` +
        head +
        metrics +
        `<div class="validation-headline">No rule violations. You can keep building without interruptions.</div>` +
        `</div>`;
      return;
    }

    const groups = {};
    issues.forEach((issue) => {
      const group = validationFieldLabel(issue && issue.field);
      if (!groups[group]) groups[group] = [];
      groups[group].push(issue);
    });

    const groupsHtml = Object.entries(groups)
      .sort((left, right) => left[0].localeCompare(right[0]))
      .map(([group, rows]) => {
        const rowHtml = rows
          .map((issue) => {
            const code = String((issue && issue.code) || "ISSUE").trim() || "ISSUE";
            const message = String((issue && issue.message) || "Rule violation.").trim();
            const refs = formatRuleRefs(issue);
            return (
              `<article class="validation-issue-row">` +
              `<div class="validation-issue-top"><span class="validation-code-pill">${esc(code)}</span></div>` +
              `<div class="validation-issue-message">${esc(message)}</div>` +
              (refs ? `<div class="validation-refs">${refs}</div>` : "") +
              `</article>`
            );
          })
          .join("");
        return (
          `<section class="validation-group">` +
          `<div class="validation-group-head">${esc(group)} <span>${esc(rows.length)}</span></div>` +
          `<div class="validation-issue-list">${rowHtml}</div>` +
          `</section>`
        );
      })
      .join("");

    root.innerHTML = `<div class="validation-panel is-invalid">${head}${metrics}<div class="validation-groups">${groupsHtml}</div></div>`;
  }

  function renderAnalysis(payload) {
    const root = document.getElementById("deck-analysis");
    if (!root) return;
    if (!payload) {
      root.innerHTML = "";
      return;
    }
    const analysis = payload.analysis || {};
    const missing = analysis.missing_cards || [];
    const replacementRows = analysis.replacement_suggestions || [];
    const replacementByCard = {};
    replacementRows.forEach((row) => {
      const key = canonicalTitle((row && row.card) || "");
      if (!key) return;
      replacementByCard[key] = Array.isArray(row.options) ? row.options : [];
    });
    const lines = missing
      .slice(0, 120)
      .map((row) => {
        const key = canonicalTitle(row.card || "");
        const options = replacementByCard[key] || [];
        const picks = options
          .slice(0, 3)
          .map((opt) => `${esc(opt.card)} (score ${esc(opt.score)} | avail ${esc(opt.available)})`)
          .join(" | ");
        const suggestion = picks ? `<div class="ok"><small>Replacements: ${picks}</small></div>` : "";
        return (
          `<div class="warn">${esc(row.card)}: need ${esc(row.required)} / owned ${esc(row.owned)} / missing ${esc(row.missing)}</div>` +
          suggestion
        );
      })
      .join("");
    root.innerHTML =
      `<div><strong>Completion:</strong> ${esc(analysis.completion_pct)}% | ` +
      `<strong>Buildable:</strong> ${analysis.is_buildable ? '<span class="ok">Yes</span>' : '<span class="err">No</span>'}</div>` +
      `<div><strong>Missing Copies:</strong> ${esc(analysis.missing_copies)} | <strong>Missing Cards:</strong> ${esc(analysis.missing_unique_cards)}</div>` +
      (lines || '<div class="ok">No missing cards for this deck.</div>');
  }

  function bindCardImageFallbacks(root) {
    if (!root) return;
    Array.from(root.querySelectorAll("img[data-fallback-src]")).forEach((img) => {
      if (img.dataset.fallbackBound === "1") return;
      img.dataset.fallbackBound = "1";
      img.addEventListener("error", () => {
        const fallback = img.getAttribute("data-fallback-src") || CARD_BACK_DEFAULT;
        if (!fallback) return;
        if (img.src && img.src.indexOf(fallback) >= 0) return;
        img.src = fallback;
        img.classList.add("is-fallback");
      });
    });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function movePreview(clientX, clientY) {
    const preview = document.getElementById("card-preview");
    if (!preview || preview.hidden) return;
    const offset = 16;
    const rect = preview.getBoundingClientRect();
    let left = clientX + offset;
    let top = clientY + offset;
    if (left + rect.width > window.innerWidth - 10) {
      left = clientX - rect.width - offset;
    }
    if (top + rect.height > window.innerHeight - 10) {
      top = clientY - rect.height - offset;
    }
    preview.style.left = `${clamp(left, 10, window.innerWidth - rect.width - 10)}px`;
    preview.style.top = `${clamp(top, 10, window.innerHeight - rect.height - 10)}px`;
  }

  function hidePreview() {
    const preview = document.getElementById("card-preview");
    if (!preview) return;
    preview.hidden = true;
  }

  function closeMainCardModal() {
    const modal = document.getElementById("main-card-modal");
    if (modal) modal.hidden = true;
  }

  function openMainCardModal(rawTitle) {
    const modal = document.getElementById("main-card-modal");
    const titleEl = document.getElementById("main-card-modal-title");
    const imageEl = document.getElementById("main-card-modal-image");
    const fallbackEl = document.getElementById("main-card-modal-fallback");
    const detailEl = document.getElementById("main-card-modal-detail");
    const metaEl = document.getElementById("main-card-modal-meta");
    const statsEl = document.getElementById("main-card-modal-stats");
    const tagsEl = document.getElementById("main-card-modal-tags");
    const effectEl = document.getElementById("main-card-modal-effect");
    const flavorEl = document.getElementById("main-card-modal-flavor");
    if (!modal || !titleEl || !imageEl || !fallbackEl || !detailEl || !metaEl || !statsEl || !tagsEl || !effectEl || !flavorEl) {
      return;
    }

    const title = canonicalTitle(rawTitle || "");
    if (!title) return;
    const card = lookupCard(title);
    const image = card && card.imageUrl ? card.imageUrl : cardBackFor(title);

    titleEl.textContent = title;
    imageEl.src = image;
    imageEl.alt = `${title} artwork`;
    imageEl.dataset.fallbackSrc = cardBackFor(title);
    imageEl.classList.toggle("is-fallback", !(card && card.imageUrl));
    imageEl.hidden = false;
    fallbackEl.hidden = true;

    const detailParts = [];
    if (card) {
      const setName = normalizeSetLabel(card.set || "");
      const rarity = normalizeRarityLabel(card.rarity || "");
      const number = String(card.cardNumber || "").trim();
      if (setName) detailParts.push(setName);
      if (rarity) detailParts.push(rarity);
      if (number) detailParts.push(`#${number}`);
    }
    detailEl.textContent = detailParts.join(" | ") || "Set / Rarity unavailable";
    metaEl.textContent = card ? cardMetaLine(card) || "Type unavailable" : "Unresolved card";
    statsEl.textContent = card ? cardStatsLine(card) || "No cost/might data" : "";
    const tags = card && Array.isArray(card.tags) ? card.tags.map((row) => String(row || "").trim()).filter(Boolean) : [];
    tagsEl.textContent = `Tags: ${tags.length ? tags.join(", ") : "-"}`;
    effectEl.textContent = (card && String(card.effect || "").trim()) || "No effect text available.";
    const flavor = card ? String(card.flavor || "").trim() : "";
    if (flavor) {
      flavorEl.textContent = flavor;
      flavorEl.hidden = false;
    } else {
      flavorEl.textContent = "";
      flavorEl.hidden = true;
    }

    bindCardImageFallbacks(modal);
    hidePreview();
    modal.hidden = false;
  }

  function showPreviewForTile(tile, clientX, clientY) {
    const preview = document.getElementById("card-preview");
    if (!preview) return;
    const title = tile.getAttribute("data-preview-title") || "Card";
    const image = tile.getAttribute("data-preview-image") || "";
    const meta = tile.getAttribute("data-preview-meta") || "";
    const stats = tile.getAttribute("data-preview-stats") || "";
    const fallback = tile.getAttribute("data-preview-fallback") || "??";

    const titleEl = document.getElementById("card-preview-title");
    const metaEl = document.getElementById("card-preview-meta");
    const statsEl = document.getElementById("card-preview-stats");
    const imageEl = document.getElementById("card-preview-image");
    const fallbackEl = document.getElementById("card-preview-fallback");
    if (!titleEl || !metaEl || !statsEl || !imageEl || !fallbackEl) return;

    titleEl.textContent = title;
    metaEl.textContent = meta || "No metadata";
    statsEl.textContent = stats || "";
    if (image) {
      const back = tile.getAttribute("data-preview-back") || CARD_BACK_DEFAULT;
      imageEl.onerror = () => {
        imageEl.onerror = null;
        imageEl.src = back;
        imageEl.classList.add("is-fallback");
      };
      imageEl.classList.toggle("is-fallback", image === back);
      imageEl.src = image;
      imageEl.alt = `${title} artwork`;
      imageEl.hidden = false;
      fallbackEl.hidden = true;
    } else {
      imageEl.hidden = true;
      fallbackEl.textContent = fallback;
      fallbackEl.hidden = false;
    }
    preview.hidden = false;
    movePreview(clientX, clientY);
  }

  function bindPreviewInteractions(root) {
    if (!root) return;
    Array.from(root.querySelectorAll("[data-preview-title]")).forEach((tile) => {
      if (tile.dataset.previewBound === "1") return;
      tile.dataset.previewBound = "1";
      tile.addEventListener("mouseenter", (ev) => {
        showPreviewForTile(tile, ev.clientX, ev.clientY);
      });
      tile.addEventListener("mousemove", (ev) => {
        movePreview(ev.clientX, ev.clientY);
      });
      tile.addEventListener("mouseleave", () => {
        hidePreview();
      });
    });
  }

  const foilMotionStates = new Map();
  const foilActiveStates = new Set();
  let foilMotionRaf = 0;

  function runFoilMotionFrame(time) {
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!foilActiveStates.size) {
      foilMotionRaf = 0;
      return;
    }

    Array.from(foilActiveStates).forEach((key) => {
      const state = foilMotionStates.get(key);
      const art = state && state.art;
      if (!art || !art.isConnected) {
        foilMotionStates.delete(key);
        foilActiveStates.delete(key);
        return;
      }

      const tile = state.tile;
      if (!tile || tile.classList.contains("is-collection-missing") || tile.classList.contains("is-unowned")) {
        art.style.setProperty("--card-mx", "50%");
        art.style.setProperty("--card-my", "50%");
        art.style.setProperty("--card-sheen-opacity", "0");
        art.style.setProperty("--foil-mx", "50%");
        art.style.setProperty("--foil-my", "50%");
        art.style.setProperty("--foil-opacity", "0.0");
        foilActiveStates.delete(key);
        return;
      }

      const ease = state.hover ? 0.12 : 0.055;
      state.currentX += (state.targetX - state.currentX) * ease;
      state.currentY += (state.targetY - state.currentY) * ease;

      let mx = state.currentX;
      let my = state.currentY;
      if (!reduceMotion) {
        const amp = state.hover ? state.idleTilt : state.idleTilt * 0.52;
        const idleX = Math.sin(time * state.idleSpeed + state.idleOffset) * amp;
        const idleY = Math.cos(time * state.idleSpeed * 0.9 + state.idleOffset) * amp;
        mx += idleX;
        my += idleY;
      }

      mx = clamp(mx, 3, 97);
      my = clamp(my, 3, 97);
      const targetSheen = state.hover ? (state.isFoil ? 0.46 : 0.32) : state.isFoil ? 0.34 : 0.22;
      const targetFoil = state.hover ? 0.94 : 0.8;
      state.sheenOpacity += (targetSheen - state.sheenOpacity) * (state.hover ? 0.16 : 0.09);
      if (state.isFoil) {
        state.foilOpacity += (targetFoil - state.foilOpacity) * (state.hover ? 0.14 : 0.08);
      }

      art.style.setProperty("--card-mx", `${mx.toFixed(2)}%`);
      art.style.setProperty("--card-my", `${my.toFixed(2)}%`);
      art.style.setProperty("--card-sheen-opacity", `${clamp(state.sheenOpacity, 0, 0.75).toFixed(3)}`);
      art.style.setProperty("--foil-mx", `${mx.toFixed(2)}%`);
      art.style.setProperty("--foil-my", `${my.toFixed(2)}%`);
      art.style.setProperty("--foil-opacity", `${clamp(state.foilOpacity, 0, 1).toFixed(3)}`);

      const settled =
        !state.hover &&
        Math.abs(state.currentX - 50) < 0.15 &&
        Math.abs(state.currentY - 50) < 0.15 &&
        Math.abs(state.sheenOpacity - (state.isFoil ? 0.34 : 0.22)) < 0.015 &&
        Math.abs(state.foilOpacity - 0.8) < 0.015;
      if (settled) {
        state.currentX = 50;
        state.currentY = 50;
        state.targetX = 50;
        state.targetY = 50;
        state.sheenOpacity = state.isFoil ? 0.34 : 0.22;
        state.foilOpacity = 0.8;
        art.style.setProperty("--card-mx", "50%");
        art.style.setProperty("--card-my", "50%");
        art.style.setProperty("--card-sheen-opacity", `${state.sheenOpacity.toFixed(3)}`);
        art.style.setProperty("--foil-mx", "50%");
        art.style.setProperty("--foil-my", "50%");
        art.style.setProperty("--foil-opacity", state.isFoil ? "0.8" : "0");
        foilActiveStates.delete(key);
      }
    });

    if (!foilActiveStates.size) {
      foilMotionRaf = 0;
      return;
    }
    foilMotionRaf = requestAnimationFrame(runFoilMotionFrame);
  }

  function ensureFoilMotionLoop() {
    if (foilMotionRaf) return;
    foilMotionRaf = requestAnimationFrame(runFoilMotionFrame);
  }

  function bindFoilInteractions(root) {
    if (!root) return;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    Array.from(root.querySelectorAll(".card-tile .card-art")).forEach((art) => {
      if (art.dataset.foilBound === "1") return;
      const tile = art.closest(".card-tile");
      if (!tile) return;
      const isFoil = tile.classList.contains("is-foil");
      art.dataset.foilBound = "1";
      art.style.setProperty("--card-mx", "50%");
      art.style.setProperty("--card-my", "50%");
      art.style.setProperty("--card-sheen-opacity", isFoil ? "0.34" : "0.22");
      art.style.setProperty("--foil-mx", "50%");
      art.style.setProperty("--foil-my", "50%");
      art.style.setProperty("--foil-opacity", isFoil ? "0.8" : "0");

      const seed = hashString(
        tile.getAttribute("data-preview-title") ||
          tile.getAttribute("data-rarity") ||
          Math.random().toString(36).slice(2)
      );
      const state = {
        art,
        tile,
        targetX: 50,
        targetY: 50,
        currentX: 50,
        currentY: 50,
        hover: false,
        isFoil,
        sheenOpacity: isFoil ? 0.34 : 0.22,
        foilOpacity: 0.8,
        idleOffset: (seed % 997) * 0.013,
        idleSpeed: 0.00014 + ((seed >>> 10) % 900) / 9000000,
        idleTilt: 1.0 + ((seed >>> 20) % 1000) / 1100
      };
      foilMotionStates.set(art, state);

      const setTargetFromPointer = (ev) => {
        const rect = art.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        state.targetX = clamp(((ev.clientX - rect.left) / rect.width) * 100, 0, 100);
        state.targetY = clamp(((ev.clientY - rect.top) / rect.height) * 100, 0, 100);
      };

      art.addEventListener("pointerenter", (ev) => {
        state.hover = true;
        setTargetFromPointer(ev);
        if (reduceMotion) {
          art.style.setProperty("--card-mx", `${state.targetX.toFixed(2)}%`);
          art.style.setProperty("--card-my", `${state.targetY.toFixed(2)}%`);
          art.style.setProperty("--card-sheen-opacity", isFoil ? "0.46" : "0.32");
          art.style.setProperty("--foil-mx", `${state.targetX.toFixed(2)}%`);
          art.style.setProperty("--foil-my", `${state.targetY.toFixed(2)}%`);
          art.style.setProperty("--foil-opacity", isFoil ? "0.94" : "0");
          return;
        }
        foilActiveStates.add(art);
        ensureFoilMotionLoop();
      });

      art.addEventListener("pointermove", (ev) => {
        setTargetFromPointer(ev);
        if (reduceMotion) {
          art.style.setProperty("--card-mx", `${state.targetX.toFixed(2)}%`);
          art.style.setProperty("--card-my", `${state.targetY.toFixed(2)}%`);
          art.style.setProperty("--foil-mx", `${state.targetX.toFixed(2)}%`);
          art.style.setProperty("--foil-my", `${state.targetY.toFixed(2)}%`);
        } else {
          foilActiveStates.add(art);
          ensureFoilMotionLoop();
        }
      });

      const reset = () => {
        state.hover = false;
        state.targetX = 50;
        state.targetY = 50;
        if (reduceMotion) {
          art.style.setProperty("--card-mx", "50%");
          art.style.setProperty("--card-my", "50%");
          art.style.setProperty("--card-sheen-opacity", isFoil ? "0.34" : "0.22");
          art.style.setProperty("--foil-mx", "50%");
          art.style.setProperty("--foil-my", "50%");
          art.style.setProperty("--foil-opacity", isFoil ? "0.8" : "0");
        } else {
          foilActiveStates.add(art);
          ensureFoilMotionLoop();
        }
      };

      art.addEventListener("pointerleave", reset);
      art.addEventListener("pointercancel", reset);
      art.addEventListener("pointerup", reset);
    });

    if (!reduceMotion && foilActiveStates.size) ensureFoilMotionLoop();
  }

  function renderCollection(snapshot, options) {
    const list = document.getElementById("collection-list");
    const summary = document.getElementById("collection-summary");
    if (!list || !summary) return;
    const opts = options || {};
    const cards = (snapshot && snapshot.cards) || {};
    const inUseCards = (snapshot && (snapshot.in_use_cards || snapshot.inUseCards)) || {};
    const availableCards = (snapshot && (snapshot.available_cards || snapshot.availableCards)) || {};
    state.collection = cards;
    state.collectionOwnedByKey = collectionKeyMap(cards);
    state.collectionInUseByKey = collectionKeyMap(inUseCards);
    state.collectionAvailableByKey = collectionKeyMap(availableCards);
    renderCollectionControls();

    const rows = collectionBrowserRows();
    const editMode = Boolean(state.ui.collectionEditMode);
    const totalOwned = Number(snapshot.total_copies || 0) || 0;
    const totalInUse = Number(snapshot.total_in_use_copies || snapshot.totalInUseCopies || 0) || 0;
    const totalAvailable = Number(snapshot.total_available_copies || snapshot.totalAvailableCopies || 0) || Math.max(0, totalOwned - totalInUse);
    summary.textContent =
      `${snapshot.total_unique_cards || 0} unique cards, ${totalOwned} owned, ${totalInUse} in use, ${totalAvailable} available` +
      (editMode ? ` | editing (${rows.length} visible cards)` : ` | ${rows.length} visible cards`);

    const tiles = rows.slice(0, 1200).map((row) => {
      const title = row.title;
      const ownedQty = Math.max(0, Number(row.qty || 0) || 0);
      const inUseQty = collectionInUseCopies(title);
      const availableQty = Math.max(0, ownedQty - inUseQty);
      const info = row.card || lookupCard(title);
      const actions = editMode
        ? `<div class="qty-stepper collection-qty-stepper">` +
          `<button type="button" class="step-btn" data-collection-dec="${escAttr(title)}"${ownedQty <= 0 ? " disabled" : ""}>-</button>` +
          `<span class="step-value">${esc(ownedQty)}</span>` +
          `<button type="button" class="step-btn" data-collection-inc="${escAttr(title)}">+</button>` +
          `</div>`
        : "";
      const usageText =
        inUseQty > 0 ? `Owned ${ownedQty} | In Use ${inUseQty} | Available ${availableQty}` : `Owned ${ownedQty}`;
      const subtitle = [info ? cardMetaLine(info) : "Unresolved card", usageText].filter(Boolean).join(" | ");
      return tileHtml({
        title,
        imageUrl: info && info.imageUrl ? info.imageUrl : "",
        badge: `x${editMode ? ownedQty : availableQty}`,
        badgeClass: "is-bottom-right",
        subtitle,
        meta: info ? cardMetaLine(info) : "",
        stats: info ? cardStatsLine(info) : "",
        actions,
        extraClass: `collection-edit-card${editMode ? " is-edit-mode" : ""}${editMode && ownedQty <= 0 ? " is-unowned" : ""}${
          inUseQty > 0 ? " is-in-use" : ""
        }`
      });
    });

    list.innerHTML =
      tiles.join("") ||
      '<div class="card-tile"><div class="card-body"><div class="card-title">No cards match the collection filters.</div></div></div>';
    bindCardImageFallbacks(list);
    bindPreviewInteractions(list);
    bindFoilInteractions(list);
    if (editMode) {
      Array.from(list.querySelectorAll("[data-collection-inc]")).forEach((btn) => {
        btn.addEventListener("click", async () => {
          const title = btn.getAttribute("data-collection-inc") || "";
          try {
            await adjustCollectionQuantity(title, 1);
            setStatus("Collection updated.", false);
          } catch (err) {
            setStatus(err.message || "Collection update failed.", true);
          }
        });
      });
      Array.from(list.querySelectorAll("[data-collection-dec]")).forEach((btn) => {
        btn.addEventListener("click", async () => {
          const title = btn.getAttribute("data-collection-dec") || "";
          try {
            await adjustCollectionQuantity(title, -1);
            setStatus("Collection updated.", false);
          } catch (err) {
            setStatus(err.message || "Collection update failed.", true);
          }
        });
      });
    }

    if (state.analysis.active && !opts.uiOnly) {
      refreshActiveAnalysisView();
      renderDeckWorkbench();
      if (state.ui.replacementCardTitle) {
        renderReplacementModal();
      }
    }
  }

  function renderLibrary() {
    const builtSelect = document.getElementById("library-built-select");
    const savedSelect = document.getElementById("library-saved-select");
    const builtGallery = document.getElementById("library-built-gallery");
    const savedGallery = document.getElementById("library-saved-gallery");
    if (!builtSelect || !savedSelect) return;

    const builtRows = [];
    const savedRows = [];
    (state.library || []).forEach((row) => {
      const bucket = String((row && row.bucket) || "saved").trim().toLowerCase();
      if (bucket === "built") builtRows.push(row);
      else savedRows.push(row);
    });

    const builtOptions = builtRows.map((row) => `<option value="${escAttr(row.id)}">${esc(row.name)} (${esc(row.source)})</option>`);
    const savedOptions = savedRows.map((row) => `<option value="${escAttr(row.id)}">${esc(row.name)} (${esc(row.source)})</option>`);
    builtSelect.innerHTML = builtOptions.join("") || '<option value="">No built decks</option>';
    savedSelect.innerHTML = savedOptions.join("") || '<option value="">No saved decks</option>';

    const renderGallery = (root, rows, bucket) => {
      if (!root) return;
      if (!rows.length) {
        root.innerHTML =
          bucket === "built"
            ? '<div class="card-tile"><div class="card-body"><div class="card-title">No built decks yet.</div><div class="card-subtitle">Built decks reserve collection cards.</div></div></div>'
            : '<div class="card-tile"><div class="card-body"><div class="card-title">No saved decks yet.</div></div></div>';
        return;
      }
      root.innerHTML = rows
        .map((row) => {
          const legendTitle = (row.deck && row.deck.legendTitle) || "";
          const info = lookupCard(legendTitle);
          const meta = info ? cardMetaLine(info) : row.source;
          const moveTo = bucket === "built" ? "saved" : "built";
          const moveLabel = moveTo === "built" ? "To Built" : "To Saved";
          const actions =
            `<button type="button" class="card-action-btn secondary" data-lib-open="${escAttr(row.id)}">Open</button>` +
            `<button type="button" class="card-action-btn" data-lib-move="${escAttr(row.id)}" data-lib-move-target="${escAttr(
              moveTo
            )}">${esc(moveLabel)}</button>`;
          return tileHtml({
            title: row.name || "Saved Deck",
            imageUrl: info && info.imageUrl ? info.imageUrl : "",
            subtitle: `${meta || row.source} | ${bucket === "built" ? "Built" : "Saved"}`,
            meta: meta,
            stats: "",
            actions
          });
        })
        .join("");
      bindCardImageFallbacks(root);
      bindPreviewInteractions(root);
      bindFoilInteractions(root);
      Array.from(root.querySelectorAll("[data-lib-open]")).forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-lib-open") || "";
          await openLibraryDeck(id);
        });
      });
      Array.from(root.querySelectorAll("[data-lib-move]")).forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-lib-move") || "";
          const target = btn.getAttribute("data-lib-move-target") || "saved";
          try {
            await setLibraryDeckBucket(id, target);
          } catch (err) {
            setStatus(err.message || "Could not move deck.", true);
          }
        });
      });
    };

    renderGallery(builtGallery, builtRows, "built");
    renderGallery(savedGallery, savedRows, "saved");
  }

  function renderMeta() {
    const root = document.getElementById("meta-list");
    if (!root) return;
    if (!state.metaDecks.length) {
      root.innerHTML = '<div class="deck-card-empty">No deck results. Try a broader search or different sort.</div>';
      return;
    }
    root.innerHTML = (state.metaDecks || [])
      .map((row, idx) => {
        const leaderInfo = lookupCard(row.leaderTitle || "");
        const metaText = row.metaScore == null ? "-" : Number(row.metaScore).toFixed(1);
        const recText = row.recommendationScore == null ? "-" : Number(row.recommendationScore).toFixed(1);
        const completionText = row.completionPct == null ? "-" : `${Number(row.completionPct).toFixed(1)}%`;
        const priceText = row.deckPrice == null ? "-" : `$${Number(row.deckPrice).toFixed(2)}`;
        const buildText =
          row.isBuildable == null ? "Build n/a" : row.isBuildable ? "Buildable" : `Missing ${row.missingCopies || 0}`;
        const subtitleParts = [`Rec ${recText}`, `Meta ${metaText}`, `Price ${priceText}`, buildText];
        const actions =
          `<button type="button" class="card-action-btn secondary" data-meta-use="${idx}">Use</button>` +
          `<button type="button" class="card-action-btn" data-meta-save="${idx}">Save</button>`;
        return tileHtml({
          title: row.deckName || "Deck",
          imageUrl: leaderInfo && leaderInfo.imageUrl ? leaderInfo.imageUrl : "",
          subtitle: subtitleParts.join(" | "),
          meta: `${row.source || "meta"} | ${leaderInfo ? cardMetaLine(leaderInfo) : canonicalTitle(row.leaderTitle || "")}`,
          stats: `Completion ${completionText}`,
          badge: buildText,
          badgeClass: "is-bottom-right",
          actions
        });
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-meta-use]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-meta-use"));
        const row = state.metaDecks[idx];
        if (!row) return;
        const nextDeck = { ...row.deck, name: row.deckName || row.deck.name };
        await writeDeckToForm(nextDeck);
        setStatus(`Loaded meta deck: ${row.deckName}`, false);
      });
    });
    Array.from(root.querySelectorAll("[data-meta-save]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-meta-save"));
        const row = state.metaDecks[idx];
        if (!row) return;
        try {
          await api("/api/decks/library", {
            method: "POST",
            body: {
              name: row.deckName,
              source: row.source,
              bucket: "saved",
              deck: row.deck
            }
          });
          await loadLibrary();
          setStatus(`Saved meta deck: ${row.deckName}`, false);
        } catch (err) {
          setStatus(err.message || "Could not save meta deck.", true);
        }
      });
    });
  }

  function metaSortByValue() {
    const select = document.getElementById("meta-sort-by");
    const raw = String((select && select.value) || "recommendation").trim().toLowerCase();
    if (!raw) return "recommendation";
    if (["recommendation", "meta", "price", "buildability"].includes(raw)) return raw;
    return "recommendation";
  }

  function metaSortDirValue(sortBy) {
    return "desc";
  }

  function domainClassFromCard(card) {
    if (!card || !Array.isArray(card.domains) || !card.domains.length) return "domain-none";
    return DOMAIN_COLOR_CLASS[card.domains[0]] || "domain-none";
  }

  function setSlotCard(slotConfig) {
    const btn = document.getElementById(slotConfig.buttonId);
    const img = document.getElementById(slotConfig.imageId);
    const name = document.getElementById(slotConfig.nameId);
    if (!btn || !img || !name) return;
    const title = String(slotConfig.title || "").trim();
    const info = lookupCard(title);
    const display = (info && info.title) || stripStarterSuffix(title) || slotConfig.placeholder;
    const image = info && info.imageUrl ? info.imageUrl : cardBackFor(display);
    img.src = image;
    img.alt = `${display} artwork`;
    img.dataset.fallbackSrc = cardBackFor(display);
    img.classList.toggle("is-fallback", !(info && info.imageUrl));
    name.textContent = display;

    btn.setAttribute("data-preview-title", display);
    btn.setAttribute("data-preview-image", image);
    btn.setAttribute("data-preview-meta", info ? cardMetaLine(info) : "");
    btn.setAttribute("data-preview-stats", info ? cardStatsLine(info) : "");
    btn.setAttribute("data-preview-fallback", initials(display));
    btn.setAttribute("data-preview-back", cardBackFor(display));

    bindCardImageFallbacks(btn);
    bindPreviewInteractions(btn);
    bindFoilInteractions(btn);
  }

  function runeSlots() {
    const legendDomains = (state.eligibility.legendDomains || [])
      .map((domain) => String(domain || "").trim())
      .filter(Boolean)
      .slice(0, 2);
    const runes = Array.isArray(state.eligibility.runes) ? state.eligibility.runes : [];

    if (!legendDomains.length) {
      return [0, 1].map((idx) => ({
        domain: "",
        domainClass: "domain-none",
        title: "",
        card: null,
        imageUrl: cardBackFor(`Rune Slot ${idx + 1}`),
        interactive: false,
        hasLegend: false
      }));
    }

    const usedRuneTitles = new Set();
    const slots = legendDomains.map((domain, idx) => {
      let card = runes.find((row) => {
        const title = String((row && row.title) || "").trim();
        return (
          Array.isArray(row.domains) &&
          row.domains.length === 1 &&
          String(row.domains[0]) === domain &&
          (!title || !usedRuneTitles.has(title))
        );
      });
      if (!card) {
        card = runes.find((row) => {
          const title = String((row && row.title) || "").trim();
          return (
            Array.isArray(row.domains) &&
            row.domains.map(String).includes(domain) &&
            (!title || !usedRuneTitles.has(title))
          );
        });
      }
      const title = card ? String(card.title || "").trim() : "";
      if (title) usedRuneTitles.add(title);
      const resolvedCard = (title && lookupCard(title)) || card || null;
      const previewName = title || `${domain} Rune`;
      return {
        domain,
        domainClass: DOMAIN_COLOR_CLASS[domain] || "domain-none",
        title,
        card: resolvedCard,
        imageUrl: resolvedCard && resolvedCard.imageUrl ? resolvedCard.imageUrl : cardBackFor(previewName),
        interactive: Boolean(title),
        hasLegend: true,
        idx
      };
    });

    while (slots.length < 2) {
      const idx = slots.length;
      slots.push({
        domain: "",
        domainClass: "domain-none",
        title: "",
        card: null,
        imageUrl: cardBackFor(`Rune Slot ${idx + 1}`),
        interactive: false,
        hasLegend: true,
        idx
      });
    }
    return slots.slice(0, 2);
  }

  function normalizeRunesToTarget() {
    const target = Number(state.eligibility.runeDeckSize || 12) || 12;
    const slots = runeSlots();
    const titles = Array.from(new Set(slots.map((slot) => slot.title).filter(Boolean)));
    const map = state.deck.runes;

    Object.keys(map).forEach((title) => {
      if (!titles.includes(title)) delete map[title];
    });

    if (!titles.length) {
      state.deck.runes = {};
      return;
    }

    if (!Object.keys(map).length && state.eligibility.recommendedRunes) {
      titles.forEach((title) => {
        const qty = Math.max(0, Number(state.eligibility.recommendedRunes[title] || 0) || 0);
        if (qty > 0) map[title] = qty;
      });
    }

    titles.forEach((title) => {
      if (!map[title]) map[title] = 0;
      map[title] = Math.max(0, Number(map[title]) || 0);
    });

    let total = titles.reduce((sum, title) => sum + (Number(map[title]) || 0), 0);
    if (total <= 0) {
      map[titles[0]] = target;
      total = target;
    }

    while (total < target) {
      const first = titles[0];
      map[first] = (map[first] || 0) + 1;
      total += 1;
    }
    while (total > target) {
      const sorted = [...titles].sort((a, b) => (map[b] || 0) - (map[a] || 0));
      const pick = sorted.find((title) => (map[title] || 0) > 0);
      if (!pick) break;
      map[pick] -= 1;
      if (map[pick] <= 0) delete map[pick];
      total -= 1;
    }
  }

  function adjustRune(title, delta) {
    if (!title || !delta) return;
    const target = Number(state.eligibility.runeDeckSize || 12) || 12;
    const titles = Array.from(
      new Set(
        runeSlots()
          .map((slot) => slot.title)
          .filter(Boolean)
      )
    );
    const map = state.deck.runes;
    if (!titles.length) return;
    if (!titles.includes(title)) return;
    if (!map[title]) map[title] = 0;

    const total = titles.reduce((sum, key) => sum + (Number(map[key]) || 0), 0);
    if (delta > 0) {
      if (total < target) {
        map[title] += 1;
      } else {
        const other = [...titles]
          .filter((entry) => entry !== title)
          .sort((a, b) => (map[b] || 0) - (map[a] || 0))
          .find((entry) => (map[entry] || 0) > 0);
        if (!other) return;
        map[other] -= 1;
        if (map[other] <= 0) delete map[other];
        map[title] += 1;
      }
    } else {
      if ((map[title] || 0) <= 0) return;
      map[title] -= 1;
      if (map[title] <= 0) delete map[title];
      const other = titles.find((entry) => entry !== title);
      if (other) map[other] = (map[other] || 0) + 1;
    }

    normalizeRunesToTarget();
    renderDeckWorkbench();
    scheduleValidation();
  }

  function eligibleMainCards(query) {
    const needle = normalizeCardKey(query || "");
    const allowed = new Set((state.eligibility.allowedMainCardTypes || ["Unit", "Gear", "Spell"]).map((v) => String(v)));
    const legendDomains = new Set((state.eligibility.legendDomains || []).map((v) => String(v)));
    const legendTags = legendChampionTagSet();
    return (state.cards || [])
      .filter((card) => {
        if (!allowed.has(card.cardType)) return false;
        if (needle && !normalizeCardKey(card.title).includes(needle)) return false;
        const signature = isSignatureCard(card);
        const cardDomains = Array.isArray(card.domains)
          ? card.domains.map((domain) => String(domain || "").trim()).filter(Boolean)
          : [];
        if (legendDomains.size && !signature) {
          if (!cardDomains.length) return false;
          const inDomain = cardDomains.every((domain) => legendDomains.has(String(domain)));
          if (!inDomain) return false;
        }
        if (legendDomains.size && signature && legendTags.size) {
          const tags = cardChampionTagSet(card);
          const hasMatchingTag = [...tags].some((tag) => legendTags.has(tag));
          if (!hasMatchingTag) return false;
        } else if (legendDomains.size && signature) {
          if (!cardDomains.length) return false;
          const inDomain = cardDomains.every((domain) => legendDomains.has(String(domain)));
          if (!inDomain) return false;
        }
        return true;
      })
      .sort((a, b) => compareCardsBySetAndNumber(a, a.title, b, b.title));
  }

  function applyMainCardDelta(title, delta) {
    const raw = String(title || "").trim();
    const key = canonicalTitle(raw);
    if (!key || !delta) return false;
    const card = lookupCard(key);
    if (card && String(card.cardType || "").trim() === "Legend") return false;
    const legendTitle = canonicalTitle(state.deck.legendTitle || "");
    if (legendTitle && key === legendTitle) return false;
    if (raw && raw !== key) {
      const aliasQty = Math.max(0, Number(state.deck.main[raw] || 0) || 0);
      if (aliasQty > 0) {
        state.deck.main[key] = (Math.max(0, Number(state.deck.main[key] || 0) || 0) || 0) + aliasQty;
        delete state.deck.main[raw];
      }
    }
    const current = Math.max(0, Number(state.deck.main[key] || 0) || 0);
    const cap = Math.max(1, mainCopyCapForTitle(key));
    if (delta > 0 && current >= cap) return false;
    const next = Math.max(0, Math.min(cap, current + delta));
    if (next === current) return false;
    if (next <= 0) {
      delete state.deck.main[key];
    } else {
      state.deck.main[key] = next;
    }
    return true;
  }

  function adjustMainCard(title, delta) {
    if (!applyMainCardDelta(title, delta)) return;
    renderDeckWorkbench();
    scheduleValidation();
  }

  function setChampionQuantity(delta) {
    const title = String(state.deck.chosenChampionTitle || "").trim();
    if (!title) return;
    adjustMainCard(title, delta);
  }

  function selectChampion(title) {
    const chosen = canonicalTitle(title);
    if (!chosen) return;
    const prev = canonicalTitle(state.deck.chosenChampionTitle || "");
    state.deck.chosenChampionTitle = chosen;
    if (prev && prev !== chosen) {
      delete state.deck.main[prev];
    }
    state.deck.main[chosen] = Math.max(1, Number(state.deck.main[chosen] || 0) || 0);
    renderDeckWorkbench();
    scheduleValidation();
  }

  function selectBattlefield(index, title) {
    const idx = Math.max(0, Math.min(2, Number(index) || 0));
    state.deck.battlefields[idx] = canonicalTitle(title);
    renderDeckWorkbench();
    scheduleValidation();
  }

  function inferChosenChampionFromDeck() {
    const current = canonicalTitle(state.deck.chosenChampionTitle || "");
    if (current) return false;
    const champions = Array.isArray(state.eligibility.champions) ? state.eligibility.champions : [];
    if (!champions.length) return false;
    const ranked = champions
      .map((card) => String((card && card.title) || "").trim())
      .filter(Boolean)
      .map((title) => ({
        title,
        qty: Math.max(0, Number(state.deck.main[title] || 0) || 0)
      }))
      .filter((row) => row.qty > 0)
      .sort((a, b) => b.qty - a.qty || a.title.localeCompare(b.title));
    if (!ranked.length) return false;
    state.deck.chosenChampionTitle = ranked[0].title;
    return true;
  }

  function sanitizeMainDeckLegendCards() {
    const main = state.deck && state.deck.main && typeof state.deck.main === "object" ? state.deck.main : {};
    const legendTitle = canonicalTitle(state.deck.legendTitle || "");
    let changed = false;

    Object.keys(main).forEach((rawTitle) => {
      const qty = Math.max(0, Number(main[rawTitle] || 0) || 0);
      const resolved = canonicalTitle(rawTitle);
      if (resolved && resolved !== rawTitle) {
        main[resolved] = (Math.max(0, Number(main[resolved] || 0) || 0) || 0) + qty;
        delete main[rawTitle];
        changed = true;
      }
    });

    Object.keys(main).forEach((title) => {
      const card = lookupCard(title);
      const isLegendType = Boolean(card) && String(card.cardType || "").trim() === "Legend";
      const isCurrentLegend = Boolean(legendTitle) && canonicalTitle(title) === legendTitle;
      if (isLegendType || isCurrentLegend) {
        delete main[title];
        changed = true;
      }
    });

    return changed;
  }

  async function refreshEligibility(legendTitle, options) {
    const opts = options || {};
    const payload = await api(
      `/api/decks/eligibility?legendTitle=${encodeURIComponent(String(legendTitle || "").trim())}&limit=1000`
    );
    state.eligibility = payload || state.eligibility;

    const champions = new Set((state.eligibility.champions || []).map((card) => card.title));
    if (state.deck.chosenChampionTitle && !champions.has(state.deck.chosenChampionTitle)) {
      delete state.deck.main[state.deck.chosenChampionTitle];
      state.deck.chosenChampionTitle = "";
    }
    sanitizeMainDeckLegendCards();
    if (opts.inferChampion) {
      inferChosenChampionFromDeck();
    }

    if (opts.applyRecommended && state.eligibility.recommendedRunes) {
      state.deck.runes = coerceCountMap(state.eligibility.recommendedRunes);
    }

    const targetBf = Math.max(1, Number(state.eligibility.battlefieldCount || 3) || 3);
    state.deck.battlefields = (state.deck.battlefields || []).map((v) => canonicalTitle(v)).slice(0, targetBf);
    while (state.deck.battlefields.length < targetBf) state.deck.battlefields.push("");

    normalizeRunesToTarget();
    renderDeckWorkbench();
    if (opts.validate !== false) {
      scheduleValidation();
    }
  }

  async function selectLegend(title) {
    state.deck.legendTitle = canonicalTitle(title);
    await refreshEligibility(state.deck.legendTitle, { applyRecommended: true, validate: true });
  }

  function mainSearchQuery() {
    const input = document.getElementById("main-card-search");
    return ((input && input.value) || "").trim();
  }

  function renderMainSearchResults() {
    const root = document.getElementById("main-search-results");
    if (!root) return;
    const query = mainSearchQuery();
    const rows = eligibleMainCards(query);
    const libraryBadge = document.getElementById("library-total-badge");
    if (libraryBadge) {
      const total = query ? eligibleMainCards("").length : rows.length;
      libraryBadge.textContent = query ? `${rows.length} / ${total} cards` : `${rows.length} cards`;
    }
    if (!rows.length) {
      root.innerHTML = '<div class="deck-card-empty">No cards match the current filters.</div>';
      return;
    }
    root.innerHTML = rows
      .map((card) => {
        const cap = Math.max(1, mainCopyCapForTitle(card.title));
        const qty = Math.max(0, Number(state.deck.main[card.title] || 0) || 0);
        const atCap = qty >= cap;
        const actions =
          `<button type="button" class="card-action-btn secondary" data-main-add="${escAttr(card.title)}"${
            atCap ? " disabled" : ""
          }>${atCap ? "Full" : "Add"}</button>`;
        return tileHtml({
          title: card.title,
          imageUrl: card.imageUrl || "",
          subtitle: cardMetaLine(card),
          meta: cardMetaLine(card),
          stats: cardStatsLine(card),
          actions,
          extraAttrs: `draggable="true" data-main-drag="${escAttr(card.title)}"`,
          extraClass: "compact"
        });
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    bindMainDragSources(root);
    Array.from(root.querySelectorAll("[data-main-add]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const title = btn.getAttribute("data-main-add") || "";
        adjustMainCard(title, 1);
      });
    });
  }

  function computeMainDeckCols(root, entryCount) {
    if (!root) return 1;
    const count = Math.max(1, Number(entryCount) || 1);
    const deckShelfStyles = window.getComputedStyle(root);
    const minCardWidth = Math.max(120, Number.parseFloat(deckShelfStyles.getPropertyValue("--main-shelf-min")) || 172);
    const cardGap = Math.max(0, Number.parseFloat(deckShelfStyles.getPropertyValue("--tile-gap")) || 18);
    const availableWidth = Math.max(0, root.clientWidth - 2);
    const estimatedCols = Math.floor((availableWidth + cardGap) / (minCardWidth + cardGap));
    return Math.max(1, Math.min(count, estimatedCols || 1));
  }

  function chunkMainDeckEntries(entries, cols) {
    const list = Array.isArray(entries) ? entries : [];
    const rowSize = Math.max(1, Number(cols) || 1);
    const rows = [];
    for (let idx = 0; idx < list.length; idx += rowSize) {
      rows.push(list.slice(idx, idx + rowSize));
    }
    return rows;
  }

  function renderMainDeckList() {
    const root = document.getElementById("main-deck-list");
    if (!root) return;
    sanitizeMainDeckLegendCards();
    refreshActiveAnalysisView();
    const entries = Object.entries(state.deck.main || {}).sort((a, b) => compareTitlesByCatalogOrder(a[0], b[0]));
    const missingByTitle = state.analysis.active ? state.analysis.mainMissingByTitle || {} : {};
    if (!entries.length) {
      root.innerHTML = '<div class="deck-card-empty">No library cards yet. Drag from A or press Add.</div>';
      bindMainDeckDropZone();
      return;
    }

    const cols = computeMainDeckCols(root, entries.length);
    const rows = chunkMainDeckEntries(entries, cols);

    root.innerHTML =
      `<div class="main-shelf-stack" style="--main-row-cols:${escAttr(cols)};">` +
      rows
        .map((rowEntries) => {
          const cards = rowEntries
            .map(([title, qty]) => {
              const card = lookupCard(title);
              const subtitle = card ? cardMetaLine(card) : "Unresolved card";
              const totalQty = Math.max(0, Number(qty) || 0);
              const missingRow = missingByTitle[title] || null;
              const missingQty = missingRow ? Math.max(0, Number(missingRow.missing || 0) || 0) : 0;
              const ownedQty = Math.max(0, totalQty - missingQty);
              const hasMissing = missingQty > 0;
              const isPartialMissing = hasMissing && ownedQty > 0;
              const chips = [];
              if (state.analysis.active && hasMissing) {
                chips.push(
                  `<button type="button" class="main-missing-chip is-missing" data-missing-open="${escAttr(title)}" title="Need ${escAttr(
                    missingQty
                  )} additional copies">0/${esc(missingQty)}</button>`
                );
              }
              const partialDuplicate = isPartialMissing
                ? `<div class="main-missing-duplicate" aria-hidden="true">` +
                  `<img src="${escAttr(card && card.imageUrl ? card.imageUrl : cardBackFor(title))}" alt="" data-fallback-src="${escAttr(
                    cardBackFor(title)
                  )}" class="${card && card.imageUrl ? "" : "is-fallback"}" />` +
                  `</div>`
                : "";
              return tileHtml({
                title,
                imageUrl: card && card.imageUrl ? card.imageUrl : "",
                subtitle,
                meta: subtitle,
                stats: card ? cardStatsLine(card) : "",
                artOverlay: partialDuplicate + (chips.length ? `<div class="main-missing-chip-stack">${chips.join("")}</div>` : ""),
                extraAttrs: hasMissing ? `data-main-missing-card="${escAttr(title)}"` : "",
                extraClass: `compact${hasMissing && !isPartialMissing ? " is-collection-missing" : ""}${isPartialMissing ? " is-collection-partial" : ""}`,
                shelfOnly: true
              });
            })
            .join("");

          const steppers = rowEntries
            .map(([title, qty]) => {
              const cap = Math.max(1, mainCopyCapForTitle(title));
              const disableInc = Number(qty) >= cap;
              return (
                `<div class="main-shelf-stepper-slot">` +
                `<div class="qty-stepper main-shelf-stepper">` +
                `<button type="button" class="step-btn" data-main-dec="${escAttr(title)}">-</button>` +
                `<span class="step-value">${esc(qty)}/${esc(cap)}</span>` +
                `<button type="button" class="step-btn" data-main-inc="${escAttr(title)}"${disableInc ? " disabled" : ""}>+</button>` +
                `</div>` +
                `</div>`
              );
            })
            .join("");

          return `<section class="main-shelf-row"><div class="main-shelf-row-cards">${cards}</div><div class="main-shelf-row-lip">${steppers}</div></section>`;
        })
        .join("") +
      `</div>`;

    bindMainDeckDropZone();
    bindCardImageFallbacks(root);
    bindFoilInteractions(root);
    bindMainDeckShelfPhysics(root);
    Array.from(root.querySelectorAll("[data-main-inc]")).forEach((btn) => {
      btn.addEventListener("click", () => adjustMainCard(btn.getAttribute("data-main-inc") || "", 1));
    });
    Array.from(root.querySelectorAll("[data-main-dec]")).forEach((btn) => {
      btn.addEventListener("click", () => adjustMainCard(btn.getAttribute("data-main-dec") || "", -1));
    });
    Array.from(root.querySelectorAll("[data-missing-open]")).forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        openReplacementModal(btn.getAttribute("data-missing-open") || "");
      });
    });
    Array.from(root.querySelectorAll(".main-shelf-row-cards .card-tile.shelf-card")).forEach((tile) => {
      if (tile.dataset.mainInfoBound === "1") return;
      tile.dataset.mainInfoBound = "1";
      tile.addEventListener("click", (ev) => {
        if (ev.target && ev.target.closest && ev.target.closest("[data-missing-open]")) return;
        const missingTitle = canonicalTitle(tile.getAttribute("data-main-missing-card") || "");
        if (missingTitle) {
          openReplacementModal(missingTitle);
          return;
        }
        const title = tile.getAttribute("data-preview-title") || "";
        openMainCardModal(title);
      });
    });
  }

  function bindMainDeckShelfPhysics(root) {
    if (!root) return;
    Array.from(root.querySelectorAll(".main-shelf-row-cards .card-tile.shelf-card")).forEach((tile) => {
      if (tile.dataset.shelfPhysicsBound === "1") return;
      tile.dataset.shelfPhysicsBound = "1";
      const art = tile.querySelector(".card-art");
      if (!art) return;

      const motion = {
        tx: 0,
        ty: 0,
        lift: 0,
        fx: 0,
        fy: 0,
        shadow: 0,
        x: 0,
        y: 0,
        l: 0,
        px: 0,
        py: 0,
        s: 0,
        raf: 0
      };

      const syncVars = () => {
        art.style.setProperty("--card-tilt-x", `${motion.x.toFixed(2)}deg`);
        art.style.setProperty("--card-tilt-y", `${motion.y.toFixed(2)}deg`);
        art.style.setProperty("--card-lift", `${motion.l.toFixed(2)}px`);
        art.style.setProperty("--card-float-x", `${motion.px.toFixed(2)}px`);
        art.style.setProperty("--card-float-y", `${motion.py.toFixed(2)}px`);
        tile.style.setProperty("--card-shadow", motion.s.toFixed(3));
        tile.style.setProperty("--card-contact-shadow", motion.s.toFixed(3));
      };

      const animate = () => {
        const stiffness = 0.2; // Slight resistance to avoid snappy movement.
        motion.x += (motion.tx - motion.x) * stiffness;
        motion.y += (motion.ty - motion.y) * stiffness;
        motion.l += (motion.lift - motion.l) * stiffness;
        motion.px += (motion.fx - motion.px) * stiffness;
        motion.py += (motion.fy - motion.py) * stiffness;
        motion.s += (motion.shadow - motion.s) * stiffness;
        syncVars();

        const delta =
          Math.abs(motion.tx - motion.x) +
          Math.abs(motion.ty - motion.y) +
          Math.abs(motion.lift - motion.l) +
          Math.abs(motion.fx - motion.px) +
          Math.abs(motion.fy - motion.py) +
          Math.abs(motion.shadow - motion.s);
        if (delta > 0.035) {
          motion.raf = requestAnimationFrame(animate);
          return;
        }
        motion.raf = 0;
        if (motion.s < 0.03) tile.classList.remove("is-phys-active");
      };

      const requestAnimation = () => {
        if (!motion.raf) motion.raf = requestAnimationFrame(animate);
      };

      const driveFromPointer = (ev) => {
        const rect = art.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        // Map pointer location in card bounds to rotation/lift vectors.
        const px = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        const py = ((ev.clientY - rect.top) / rect.height) * 2 - 1;
        const nx = Math.max(-1, Math.min(1, px));
        const ny = Math.max(-1, Math.min(1, py));
        const center = 1 - Math.min(1, Math.hypot(nx, ny));

        motion.tx = -(ny * 7);
        motion.ty = nx * 9;
        motion.lift = -(6 + center * 3.6);
        motion.fx = nx * 1.5;
        motion.fy = -(center * 1.2);
        motion.shadow = 0.45 + center * 0.55;

        tile.classList.add("is-phys-active");
        requestAnimation();
      };

      const reset = () => {
        motion.tx = 0;
        motion.ty = 0;
        motion.lift = 0;
        motion.fx = 0;
        motion.fy = 0;
        motion.shadow = 0;
        requestAnimation();
      };

      tile.addEventListener("pointerenter", driveFromPointer);
      tile.addEventListener("pointermove", driveFromPointer);
      tile.addEventListener("pointerleave", reset);
      tile.addEventListener("pointercancel", reset);
      tile.addEventListener("pointerup", reset);
    });
  }

  function bindMainDragSources(root) {
    if (!root) return;
    Array.from(root.querySelectorAll("[data-main-drag]")).forEach((tile) => {
      if (tile.dataset.mainDragBound === "1") return;
      tile.dataset.mainDragBound = "1";
      tile.addEventListener("dragstart", (ev) => {
        const title = tile.getAttribute("data-main-drag") || "";
        if (!title || !ev.dataTransfer) return;
        ev.dataTransfer.setData("text/plain", title);
        ev.dataTransfer.effectAllowed = "copy";
        tile.classList.add("is-dragging");
      });
      tile.addEventListener("dragend", () => {
        tile.classList.remove("is-dragging");
      });
    });
  }

  function bindMainDeckDropZone() {
    const root = document.getElementById("main-deck-list");
    if (!root || root.dataset.mainDropBound === "1") return;
    root.dataset.mainDropBound = "1";
    root.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      root.classList.add("is-drop-target");
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
    });
    root.addEventListener("dragenter", (ev) => {
      ev.preventDefault();
      root.classList.add("is-drop-target");
    });
    root.addEventListener("dragleave", () => {
      root.classList.remove("is-drop-target");
    });
    root.addEventListener("drop", (ev) => {
      ev.preventDefault();
      root.classList.remove("is-drop-target");
      const title = (ev.dataTransfer && ev.dataTransfer.getData("text/plain")) || "";
      if (!title) return;
      adjustMainCard(title, 1);
    });
  }

  function renderRuneSteppers() {
    const root = document.getElementById("rune-stepper-list");
    if (!root) return;
    const slots = runeSlots();
    const hasLegend = slots.some((slot) => Boolean(slot.domain));
    root.innerHTML = slots
      .map((slot, idx) => {
        const displayName = slot.title || slot.domain || `Rune Slot ${idx + 1}`;
        const qty = slot.title ? Math.max(0, Number(state.deck.runes[slot.title] || 0) || 0) : 0;
        const previewMeta = slot.card ? cardMetaLine(slot.card) : slot.domain ? `Rune | ${slot.domain}` : "";
        const previewStats = slot.card ? cardStatsLine(slot.card) : "";
        const controls =
          hasLegend && slot.interactive
            ? `<div class="qty-stepper rune-slot-stepper">` +
              `<button type="button" class="step-btn" data-rune-dec="${escAttr(slot.title)}">-</button>` +
              `<span class="step-value">${esc(qty)}</span>` +
              `<button type="button" class="step-btn" data-rune-inc="${escAttr(slot.title)}">+</button>` +
              `</div>`
            : "";
        const meta =
          hasLegend
            ? `<div class="rune-slot-meta">` +
              `<div class="rune-slot-domain"><span class="rune-dot ${esc(slot.domainClass)}"></span>${esc(slot.domain || "Unassigned")}</div>` +
              `<div class="rune-slot-title">${esc(slot.title || "No matching rune card")}</div>` +
              `</div>`
            : "";
        return (
          `<article class="rune-slot-card ${hasLegend ? "" : "is-back-only"} ${slot.interactive ? "" : "is-disabled"}"` +
          ` data-preview-title="${escAttr(displayName)}"` +
          ` data-preview-image="${escAttr(slot.imageUrl)}"` +
          ` data-preview-meta="${escAttr(previewMeta)}"` +
          ` data-preview-stats="${escAttr(previewStats)}"` +
          ` data-preview-fallback="${escAttr(initials(displayName))}"` +
          ` data-preview-back="${escAttr(cardBackFor(displayName))}">` +
          `<div class="rune-slot-art-wrap">` +
          `<img class="rune-slot-art ${slot.card && slot.card.imageUrl ? "" : "is-fallback"}" src="${escAttr(slot.imageUrl)}" alt="${escAttr(
            displayName
          )} artwork" data-fallback-src="${escAttr(cardBackFor(displayName))}" />` +
          `</div>` +
          meta +
          controls +
          `</article>`
        );
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-rune-inc]")).forEach((btn) => {
      btn.addEventListener("click", () => adjustRune(btn.getAttribute("data-rune-inc") || "", 1));
    });
    Array.from(root.querySelectorAll("[data-rune-dec]")).forEach((btn) => {
      btn.addEventListener("click", () => adjustRune(btn.getAttribute("data-rune-dec") || "", -1));
    });
  }

  function renderBattlefieldSlots() {
    const root = document.getElementById("battlefield-slots");
    if (!root) return;
    const target = Math.max(1, Number(state.eligibility.battlefieldCount || 3) || 3);
    const slots = (state.deck.battlefields || []).slice(0, target);
    while (slots.length < target) slots.push("");

    root.innerHTML = slots
      .map((title, idx) => {
        const clean = stripStarterSuffix(String(title || "").trim());
        const card = lookupCard(clean);
        const display = clean || `Choose Battlefield ${idx + 1}`;
        const image = card && card.imageUrl ? card.imageUrl : cardBackFor(display);
        const meta = card ? cardMetaLine(card) : "";
        return (
          `<button type="button" class="slot-card battlefield-slot-card" data-bf-slot="${idx}"` +
          ` data-preview-title="${escAttr(display)}"` +
          ` data-preview-image="${escAttr(image)}"` +
          ` data-preview-meta="${escAttr(meta)}"` +
          ` data-preview-stats="${escAttr(card ? cardStatsLine(card) : "")}"` +
          ` data-preview-fallback="${escAttr(initials(display))}"` +
          ` data-preview-back="${escAttr(cardBackFor(display))}">` +
          `<div class="slot-card-art-wrap"><img class="slot-card-art ${card && card.imageUrl ? "" : "is-fallback"}" src="${escAttr(image)}" alt="${escAttr(
            display
          )} artwork" data-fallback-src="${escAttr(cardBackFor(display))}" /></div>` +
          `<div class="slot-card-name">${esc(display)}</div>` +
          `</button>`
        );
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    Array.from(root.querySelectorAll("[data-bf-slot]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        openPicker("battlefield", Number(btn.getAttribute("data-bf-slot") || 0));
      });
    });
  }

  function renderDeckWorkbench() {
    refreshActiveAnalysisView();
    const deckName = document.getElementById("deck-name");
    if (deckName && deckName.value !== state.deck.name) {
      deckName.value = state.deck.name;
    }

    setSlotCard({
      buttonId: "legend-slot-btn",
      imageId: "legend-slot-img",
      nameId: "legend-slot-name",
      title: state.deck.legendTitle,
      placeholder: "Choose Legend"
    });

    setSlotCard({
      buttonId: "champion-slot-btn",
      imageId: "champion-slot-img",
      nameId: "champion-slot-name",
      title: state.deck.chosenChampionTitle,
      placeholder: "Choose Champion"
    });

    const championQtyEl = document.getElementById("champion-qty-value");
    if (championQtyEl) {
      const qty = state.deck.chosenChampionTitle ? Number(state.deck.main[state.deck.chosenChampionTitle] || 0) || 0 : 0;
      championQtyEl.textContent = String(qty);
    }

    const runeBadge = document.getElementById("rune-total-badge");
    if (runeBadge) {
      runeBadge.textContent = `${runeTotal()} / ${state.eligibility.runeDeckSize || 12}`;
    }

    const mainBadge = document.getElementById("main-total-badge");
    if (mainBadge) {
      const target = state.eligibility.mainDeckSize || 40;
      if (state.analysis.active) {
        mainBadge.textContent = `${state.analysis.mainOwnedCopies || 0} / ${target}`;
        mainBadge.classList.add("is-analysis-active");
      } else {
        mainBadge.textContent = `${mainTotal()} / ${target}`;
        mainBadge.classList.remove("is-analysis-active");
      }
    }

    renderRuneSteppers();
    renderBattlefieldSlots();
    renderMainSearchResults();
    renderMainDeckList();
  }

  function closeReplacementModal() {
    state.ui.replacementCardTitle = "";
    const modal = document.getElementById("replacement-modal");
    if (modal) modal.hidden = true;
  }

  function replacementOptionsForCard(title) {
    const key = canonicalTitle(title);
    const raw = (state.analysis.replacementByCard && state.analysis.replacementByCard[key]) || [];
    return raw
      .map((opt) => {
        const cardTitle = canonicalTitle((opt && opt.card) || "");
        if (!cardTitle || cardTitle === key) return null;
        const cap = Math.max(1, mainCopyCapForTitle(cardTitle));
        const current = Math.max(0, Number(state.deck.main[cardTitle] || 0) || 0);
        const legalSlots = Math.max(0, cap - current);
        const available = Math.max(0, Number(opt.available || 0) || 0);
        const addable = Math.min(available, legalSlots);
        return {
          card: cardTitle,
          owned: Math.max(0, Number(opt.owned || 0) || 0),
          available,
          addable,
          score: Number(opt.score || 0) || 0
        };
      })
      .filter((row) => row && row.addable > 0)
      .slice(0, 6);
  }

  function renderReplacementModal() {
    const modal = document.getElementById("replacement-modal");
    const nameEl = document.getElementById("replacement-target-name");
    const metaEl = document.getElementById("replacement-target-meta");
    const stateEl = document.getElementById("replacement-target-state");
    const imageEl = document.getElementById("replacement-target-image");
    const titleEl = document.getElementById("replacement-title");
    const summaryEl = document.getElementById("replacement-summary");
    const optionsEl = document.getElementById("replacement-options");
    if (!modal || !nameEl || !metaEl || !stateEl || !imageEl || !titleEl || !summaryEl || !optionsEl) return;

    const targetTitle = canonicalTitle(state.ui.replacementCardTitle || "");
    if (!targetTitle || !state.analysis.active) {
      modal.hidden = true;
      return;
    }

    const missingRow = state.analysis.mainMissingByTitle[targetTitle];
    if (!missingRow || missingRow.missing <= 0) {
      modal.hidden = true;
      return;
    }

    const card = lookupCard(targetTitle);
    const image = card && card.imageUrl ? card.imageUrl : cardBackFor(targetTitle);
    imageEl.src = image;
    imageEl.alt = `${targetTitle} artwork`;
    imageEl.dataset.fallbackSrc = cardBackFor(targetTitle);
    imageEl.classList.toggle("is-fallback", !(card && card.imageUrl));
    nameEl.textContent = targetTitle;
    metaEl.textContent = card ? cardMetaLine(card) : "Unresolved card";
    stateEl.textContent = `Owned ${missingRow.owned}/${missingRow.required} | Missing ${missingRow.missing}`;
    titleEl.textContent = `Replace Missing Copies: ${targetTitle}`;
    summaryEl.textContent =
      missingRow.missing === 1
        ? "Choose one legal replacement."
        : `Choose up to ${missingRow.missing} legal replacements.`;

    const options = replacementOptionsForCard(targetTitle);
    if (!options.length) {
      optionsEl.innerHTML = '<div class="replacement-empty">No legal replacement cards are currently addable from your collection.</div>';
      bindCardImageFallbacks(modal);
      modal.hidden = false;
      return;
    }

    optionsEl.innerHTML = options
      .map((row, idx) => {
        const info = lookupCard(row.card);
        const imageUrl = info && info.imageUrl ? info.imageUrl : cardBackFor(row.card);
        const rowClass = idx < 3 ? "is-top-shelf" : "is-bottom-shelf";
        return (
          `<article class="replacement-option ${rowClass}">` +
          `<div class="replacement-option-art-wrap">` +
          `<img class="replacement-option-image ${info && info.imageUrl ? "" : "is-fallback"}" src="${escAttr(imageUrl)}" alt="${escAttr(
            row.card
          )} artwork" data-fallback-src="${escAttr(cardBackFor(row.card))}" />` +
          `<span class="replacement-owned-badge">x${esc(row.owned)}</span>` +
          `</div>` +
          `<div class="replacement-option-title" title="${escAttr(row.card)}">${esc(row.card)}</div>` +
          `<div class="replacement-option-metrics">Score ${esc(row.score.toFixed(2))} | Addable ${esc(row.addable)}</div>` +
          `<button type="button" class="card-action-btn secondary replacement-use-btn" data-replace-use="${escAttr(
            row.card
          )}" data-replace-target="${escAttr(targetTitle)}">Add to Deck</button>` +
          `</article>`
        );
      })
      .join("");

    bindCardImageFallbacks(modal);
    bindFoilInteractions(modal);
    Array.from(optionsEl.querySelectorAll("[data-replace-use]")).forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const cardTitle = btn.getAttribute("data-replace-use") || "";
        const missingTitle = btn.getAttribute("data-replace-target") || "";
        await applyReplacementChoice(missingTitle, cardTitle);
      });
    });

    modal.hidden = false;
  }

  function openReplacementModal(title) {
    const target = canonicalTitle(title);
    if (!target || !state.analysis.active) return;
    const missingRow = state.analysis.mainMissingByTitle[target];
    if (!missingRow || missingRow.missing <= 0) return;
    state.ui.replacementCardTitle = target;
    renderReplacementModal();
    if (!state.analysis.replacementByCard[target]) {
      void runAnalysis()
        .then(() => {
          if (state.analysis.mainMissingByTitle[target]) {
            state.ui.replacementCardTitle = target;
            renderReplacementModal();
          }
        })
        .catch(() => {});
    }
  }

  async function applyReplacementChoice(missingCardTitle, replacementCardTitle) {
    const target = canonicalTitle(missingCardTitle);
    const replacement = canonicalTitle(replacementCardTitle);
    if (!target || !replacement) return;
    if (target === replacement) return;
    const missingRow = state.analysis.mainMissingByTitle[target];
    if (!missingRow || missingRow.missing <= 0) {
      closeReplacementModal();
      return;
    }
    const decOk = applyMainCardDelta(target, -1);
    if (!decOk) return;
    const incOk = applyMainCardDelta(replacement, 1);
    if (!incOk) {
      applyMainCardDelta(target, 1);
      setStatus("Replacement card is at its legal copy cap.", true);
      return;
    }

    renderDeckWorkbench();
    try {
      await runAnalysis();
      const stillMissing = state.analysis.mainMissingByTitle[target];
      if (stillMissing && stillMissing.missing > 0) {
        state.ui.replacementCardTitle = target;
        renderReplacementModal();
      } else {
        closeReplacementModal();
      }
    } catch (err) {
      setStatus(err.message || "Could not refresh analysis after replacement.", true);
    }
  }

  function closePicker() {
    state.picker.kind = "";
    state.picker.battlefieldIndex = 0;
    const modal = document.getElementById("card-picker-modal");
    if (modal) modal.hidden = true;
    const input = document.getElementById("picker-search-input");
    if (input) input.value = "";
  }

  function pickerCards(kind, query) {
    const needle = normalizeCardKey(query || "");
    let rows = [];
    if (kind === "legend") rows = state.eligibility.legends || [];
    else if (kind === "champion") rows = state.eligibility.champions || [];
    else if (kind === "battlefield") rows = state.eligibility.battlefields || [];
    else if (kind === "main") rows = eligibleMainCards(query);

    if (!needle || kind === "main") return rows;
    return rows.filter((card) => normalizeCardKey(card.title).includes(needle));
  }

  function renderPickerGrid() {
    const root = document.getElementById("picker-grid");
    const input = document.getElementById("picker-search-input");
    if (!root || !input) return;
    const kind = state.picker.kind;
    const query = String(input.value || "").trim();
    const rows = pickerCards(kind, query).slice(0, 120);
    if (!rows.length) {
      root.innerHTML = '<div class="deck-card-empty">No cards match this query.</div>';
      return;
    }
    root.innerHTML = rows
      .map((card) => {
        const actions = `<button type="button" class="card-action-btn secondary" data-picker-select="${escAttr(card.title)}">Select</button>`;
        return tileHtml({
          title: card.title,
          imageUrl: card.imageUrl || "",
          subtitle: cardMetaLine(card),
          meta: cardMetaLine(card),
          stats: cardStatsLine(card),
          actions,
          extraClass: "compact"
        });
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-picker-select]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const title = btn.getAttribute("data-picker-select") || "";
        if (state.picker.kind === "legend") {
          await selectLegend(title);
        } else if (state.picker.kind === "champion") {
          selectChampion(title);
        } else if (state.picker.kind === "battlefield") {
          selectBattlefield(state.picker.battlefieldIndex, title);
        } else if (state.picker.kind === "main") {
          adjustMainCard(title, 1);
        }
        closePicker();
      });
    });
  }

  function openPicker(kind, battlefieldIndex) {
    state.picker.kind = String(kind || "");
    state.picker.battlefieldIndex = Number(battlefieldIndex || 0) || 0;
    const modal = document.getElementById("card-picker-modal");
    const title = document.getElementById("picker-title");
    const input = document.getElementById("picker-search-input");
    if (!modal || !title || !input) return;

    if (kind === "legend") title.textContent = "Choose Legend";
    else if (kind === "champion") title.textContent = "Choose Chosen Champion";
    else if (kind === "battlefield") title.textContent = "Choose Battlefield";
    else title.textContent = "Add Main-Deck Card";

    input.value = "";
    modal.hidden = false;
    renderPickerGrid();
    input.focus();
  }

  async function runValidation() {
    const payload = await api("/api/decks/validate", {
      method: "POST",
      body: { deck: currentDeckFromForm() }
    });
    state.lastValidation = payload;
    renderValidation(payload);
    setLegalityIndicator(payload);
    setStatus(payload.is_valid ? "Legal" : "Illegal", !payload.is_valid);
    return payload;
  }

  function scheduleValidation(immediate) {
    if (state.validateTimer) {
      clearTimeout(state.validateTimer);
      state.validateTimer = null;
    }
    if (immediate) {
      void runValidation().catch((err) => {
        setStatus(err.message || "Validation failed.", true);
      });
      return;
    }
    state.validateTimer = setTimeout(() => {
      void runValidation().catch((err) => {
        setStatus(err.message || "Validation failed.", true);
      });
    }, 200);
  }

  async function runAnalysis() {
    const payload = await api("/api/decks/analyze", {
      method: "POST",
      body: { deck: currentDeckFromForm() }
    });
    applyAnalysisSnapshot(payload);
    state.lastValidation = payload.validation;
    renderValidation(payload.validation);
    setLegalityIndicator(payload.validation);
    renderAnalysis(payload);
    renderDeckWorkbench();
    if (state.ui.replacementCardTitle) {
      renderReplacementModal();
    }
    setStatus(payload.validation && payload.validation.is_valid ? "Legal" : "Illegal", !(payload.validation || {}).is_valid);
    return payload;
  }

  async function loadCardCatalog() {
    try {
      const rows = await api("/api/cards?limit=1200");
      state.cards = rows || [];
      state.cardsByTitle = {};
      state.cardsByKey = {};
      (rows || []).forEach((card) => {
        if (!card || !card.title) return;
        state.cardsByTitle[card.title] = card;
        const key = normalizeCardKey(card.title);
        if (key && !state.cardsByKey[key]) {
          state.cardsByKey[key] = card;
        }
      });
    } catch (_err) {
      state.cards = [];
      state.cardsByTitle = {};
      state.cardsByKey = {};
    }
  }

  async function loadCollection() {
    const root = document.getElementById("collection-list");
    if (root) root.innerHTML = skeletonTiles(8);
    const payload = await api("/api/collection");
    renderCollection(payload);
  }

  async function loadLibrary() {
    const builtRoot = document.getElementById("library-built-gallery");
    const savedRoot = document.getElementById("library-saved-gallery");
    if (builtRoot) builtRoot.innerHTML = skeletonTiles(2);
    if (savedRoot) savedRoot.innerHTML = skeletonTiles(2);
    state.library = await api("/api/decks/library");
    renderLibrary();
  }

  async function loadMetaDecks() {
    const root = document.getElementById("meta-list");
    if (root) root.innerHTML = skeletonTiles(6);
    const query = ((document.getElementById("meta-search") || {}).value || "").trim();
    const sortBy = metaSortByValue();
    const sortDir = metaSortDirValue(sortBy);
    state.metaDecks = await api(
      `/api/meta/decks?limit=120&query=${encodeURIComponent(query)}&sortBy=${encodeURIComponent(sortBy)}&sortDir=${encodeURIComponent(
        sortDir
      )}&includeCollection=true`
    );
    renderMeta();
  }

  async function refreshMetaSearchResults() {
    try {
      await loadMetaDecks();
    } catch (_err) {
      // Keep write actions successful even if deck-search refresh fails.
    }
  }

  async function importCollectionCsv() {
    const fileInput = document.getElementById("collection-csv-file");
    if (!fileInput || !fileInput.files || !fileInput.files.length) {
      throw new Error("Choose a CSV file first.");
    }
    const csvText = await fileInput.files[0].text();
    const payload = await api("/api/collection/import-csv", {
      method: "POST",
      body: { csvText, replaceExisting: false }
    });
    renderCollection(payload);
  }

  function downloadJson(filename, value) {
    const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function writeDeckToForm(deck) {
    state.deck = normalizeDeckPayload(deck);
    sanitizeMainDeckLegendCards();
    await refreshEligibility(state.deck.legendTitle, { applyRecommended: false, inferChampion: true, validate: false });
    setWorkspaceTab("deck");
    renderDeckWorkbench();
    scheduleValidation(true);
  }

  async function openLibraryDeck(deckId) {
    const id = String(deckId || "");
    if (!id) return;
    const row = state.library.find((entry) => String(entry.id) === id);
    if (!row || !row.deck) return;
    const deck = { ...row.deck, name: row.name || row.deck.name };
    await writeDeckToForm(deck);
    const builtSelect = document.getElementById("library-built-select");
    const savedSelect = document.getElementById("library-saved-select");
    if (builtSelect && Array.from(builtSelect.options || []).some((opt) => String(opt.value) === id)) builtSelect.value = id;
    if (savedSelect && Array.from(savedSelect.options || []).some((opt) => String(opt.value) === id)) savedSelect.value = id;
    setStatus(`Loaded "${row.name}".`, false);
  }

  async function setLibraryDeckBucket(deckId, bucket) {
    const id = String(deckId || "");
    const nextBucket = String(bucket || "").trim().toLowerCase() === "built" ? "built" : "saved";
    if (!id) return;
    await api(`/api/decks/library/${encodeURIComponent(id)}/bucket`, {
      method: "PUT",
      body: { bucket: nextBucket }
    });
    await Promise.all([loadLibrary(), loadCollection(), refreshMetaSearchResults()]);
    setStatus(nextBucket === "built" ? "Deck moved to Built Decks." : "Deck moved to Saved Decks.", false);
  }

  function bindEvents() {
    Array.from(document.querySelectorAll("[data-workspace-tab]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        setWorkspaceTab(btn.getAttribute("data-workspace-tab") || "deck");
      });
    });

    const deckNameInput = document.getElementById("deck-name");
    if (deckNameInput) {
      deckNameInput.addEventListener("input", () => {
        state.deck.name = String(deckNameInput.value || "").trim() || "Untitled Deck";
      });
    }

    const legendBtn = document.getElementById("legend-slot-btn");
    if (legendBtn) {
      legendBtn.addEventListener("click", () => openPicker("legend", 0));
    }

    const championBtn = document.getElementById("champion-slot-btn");
    if (championBtn) {
      championBtn.addEventListener("click", () => {
        if (!state.deck.legendTitle) {
          setStatus("Choose a legend first.", true);
          return;
        }
        openPicker("champion", 0);
      });
    }

    const championDec = document.getElementById("champion-qty-dec");
    if (championDec) championDec.addEventListener("click", () => setChampionQuantity(-1));
    const championInc = document.getElementById("champion-qty-inc");
    if (championInc) championInc.addEventListener("click", () => setChampionQuantity(1));

    const mainSearchBtn = document.getElementById("main-card-search-btn");
    if (mainSearchBtn) {
      mainSearchBtn.addEventListener("click", () => {
        const input = document.getElementById("main-card-search");
        if (!input) return;
        input.value = "";
        renderMainSearchResults();
      });
    }

    const mainSearchInput = document.getElementById("main-card-search");
    if (mainSearchInput) {
      mainSearchInput.addEventListener("input", () => renderMainSearchResults());
      mainSearchInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
        }
      });
    }
    bindMainDeckDropZone();

    Array.from(document.querySelectorAll("[data-section-expand]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleDeckSectionFocus(btn.getAttribute("data-section-expand") || "");
      });
    });

    const pickerClose = document.getElementById("picker-close-btn");
    if (pickerClose) pickerClose.addEventListener("click", closePicker);

    const pickerSearch = document.getElementById("picker-search-input");
    if (pickerSearch) {
      pickerSearch.addEventListener("input", () => renderPickerGrid());
    }

    const pickerModal = document.getElementById("card-picker-modal");
    if (pickerModal) {
      pickerModal.addEventListener("click", (ev) => {
        if (ev.target === pickerModal) closePicker();
      });
    }

    const replacementClose = document.getElementById("replacement-close-btn");
    if (replacementClose) replacementClose.addEventListener("click", closeReplacementModal);

    const replacementModal = document.getElementById("replacement-modal");
    if (replacementModal) {
      replacementModal.addEventListener("click", (ev) => {
        if (ev.target === replacementModal) closeReplacementModal();
      });
    }

    const mainCardClose = document.getElementById("main-card-modal-close");
    if (mainCardClose) mainCardClose.addEventListener("click", closeMainCardModal);

    const mainCardModal = document.getElementById("main-card-modal");
    if (mainCardModal) {
      mainCardModal.addEventListener("click", (ev) => {
        if (ev.target === mainCardModal) closeMainCardModal();
      });
    }

    const collectionImportBtn = document.getElementById("collection-import-btn");
    const collectionFileInput = document.getElementById("collection-csv-file");
    if (collectionImportBtn && collectionFileInput) {
      collectionImportBtn.addEventListener("click", () => {
        collectionFileInput.click();
      });
      collectionFileInput.addEventListener("change", async () => {
        if (!collectionFileInput.files || !collectionFileInput.files.length) return;
        try {
          await importCollectionCsv();
          await refreshMetaSearchResults();
          setStatus("Collection CSV imported.", false);
        } catch (err) {
          setStatus(err.message || "CSV import failed.", true);
        } finally {
          collectionFileInput.value = "";
        }
      });
    }

    const collectionSearchInput = document.getElementById("collection-search-input");
    if (collectionSearchInput) {
      collectionSearchInput.addEventListener("input", () => {
        state.ui.collectionSearch = String(collectionSearchInput.value || "").trim();
        rerenderCollectionFromState();
      });
    }

    const collectionFilterToggleBtn = document.getElementById("collection-filter-toggle-btn");
    if (collectionFilterToggleBtn) {
      collectionFilterToggleBtn.addEventListener("click", () => {
        state.ui.collectionFiltersOpen = !state.ui.collectionFiltersOpen;
        rerenderCollectionFromState();
      });
    }

    const collectionEditToggleBtn = document.getElementById("collection-edit-toggle-btn");
    if (collectionEditToggleBtn) {
      collectionEditToggleBtn.addEventListener("click", () => {
        state.ui.collectionEditMode = !state.ui.collectionEditMode;
        rerenderCollectionFromState();
      });
    }

    ["collection-filter-set", "collection-filter-rarity", "collection-filter-domain", "collection-filter-role"].forEach((id) => {
      const select = document.getElementById(id);
      if (!select) return;
      select.addEventListener("change", () => {
        if (id === "collection-filter-set") state.ui.collectionFilters.set = String(select.value || "");
        else if (id === "collection-filter-rarity") state.ui.collectionFilters.rarity = String(select.value || "");
        else if (id === "collection-filter-domain") state.ui.collectionFilters.domain = String(select.value || "");
        else if (id === "collection-filter-role") state.ui.collectionFilters.role = String(select.value || "");
        rerenderCollectionFromState();
      });
    });

    const collectionFilterClearBtn = document.getElementById("collection-filter-clear-btn");
    if (collectionFilterClearBtn) {
      collectionFilterClearBtn.addEventListener("click", () => {
        state.ui.collectionFilters = { set: "", rarity: "", domain: "", role: "" };
        rerenderCollectionFromState();
      });
    }

    document.getElementById("deck-validate-btn").addEventListener("click", async () => {
      try {
        await runValidation();
      } catch (err) {
        setStatus(err.message || "Validation failed.", true);
      }
    });

    document.getElementById("deck-analyze-btn").addEventListener("click", async () => {
      try {
        await runAnalysis();
      } catch (err) {
        setStatus(err.message || "Analysis failed.", true);
      }
    });

    document.getElementById("deck-save-btn").addEventListener("click", async () => {
      try {
        const deck = currentDeckFromForm();
        await api("/api/decks/library", {
          method: "POST",
          body: { name: deck.name, source: deck.source, bucket: "built", deck }
        });
        await Promise.all([loadLibrary(), loadCollection(), refreshMetaSearchResults()]);
        if (state.lastValidation && !state.lastValidation.is_valid) {
          setStatus("Deck saved (currently illegal).", true);
        } else {
          setStatus("Deck saved to library.", false);
        }
      } catch (err) {
        setStatus(err.message || "Could not save deck.", true);
      }
    });

    const loadDeckFromSelect = async (selectId) => {
      const id = (document.getElementById(selectId) || {}).value || "";
      if (!id) return;
      await openLibraryDeck(id);
    };

    const updateDeckFromSelect = async (selectId, bucket) => {
      const id = (document.getElementById(selectId) || {}).value || "";
      if (!id) {
        setStatus("Choose a deck to update.", true);
        return;
      }
      try {
        const deck = currentDeckFromForm();
        await api(`/api/decks/library/${encodeURIComponent(id)}`, {
          method: "PUT",
          body: { name: deck.name, source: deck.source, bucket, deck }
        });
        await Promise.all([loadLibrary(), loadCollection(), refreshMetaSearchResults()]);
        setStatus("Deck updated.", false);
      } catch (err) {
        setStatus(err.message || "Could not update deck.", true);
      }
    };

    const deleteDeckFromSelect = async (selectId, label) => {
      const id = (document.getElementById(selectId) || {}).value || "";
      if (!id) return;
      if (!window.confirm(`Delete this ${label}?`)) return;
      try {
        await api(`/api/decks/library/${encodeURIComponent(id)}`, { method: "DELETE" });
        await Promise.all([loadLibrary(), loadCollection(), refreshMetaSearchResults()]);
        setStatus("Deck deleted.", false);
      } catch (err) {
        setStatus(err.message || "Could not delete deck.", true);
      }
    };

    const moveDeckFromSelect = async (selectId, targetBucket, label) => {
      const id = (document.getElementById(selectId) || {}).value || "";
      if (!id) return;
      try {
        await setLibraryDeckBucket(id, targetBucket);
      } catch (err) {
        setStatus(err.message || `Could not move ${label}.`, true);
      }
    };

    const builtLoadBtn = document.getElementById("library-built-load-btn");
    if (builtLoadBtn) builtLoadBtn.addEventListener("click", () => void loadDeckFromSelect("library-built-select"));
    const savedLoadBtn = document.getElementById("library-saved-load-btn");
    if (savedLoadBtn) savedLoadBtn.addEventListener("click", () => void loadDeckFromSelect("library-saved-select"));

    const builtUpdateBtn = document.getElementById("library-built-update-btn");
    if (builtUpdateBtn) builtUpdateBtn.addEventListener("click", () => void updateDeckFromSelect("library-built-select", "built"));
    const savedUpdateBtn = document.getElementById("library-saved-update-btn");
    if (savedUpdateBtn) savedUpdateBtn.addEventListener("click", () => void updateDeckFromSelect("library-saved-select", "saved"));

    const builtDeleteBtn = document.getElementById("library-built-delete-btn");
    if (builtDeleteBtn) builtDeleteBtn.addEventListener("click", () => void deleteDeckFromSelect("library-built-select", "built deck"));
    const savedDeleteBtn = document.getElementById("library-saved-delete-btn");
    if (savedDeleteBtn) savedDeleteBtn.addEventListener("click", () => void deleteDeckFromSelect("library-saved-select", "saved deck"));

    const builtMoveBtn = document.getElementById("library-built-move-btn");
    if (builtMoveBtn) builtMoveBtn.addEventListener("click", () => void moveDeckFromSelect("library-built-select", "saved", "deck"));
    const savedMoveBtn = document.getElementById("library-saved-move-btn");
    if (savedMoveBtn) savedMoveBtn.addEventListener("click", () => void moveDeckFromSelect("library-saved-select", "built", "deck"));

    document.getElementById("deck-export-btn").addEventListener("click", () => {
      const deck = currentDeckFromForm();
      downloadJson(`${(deck.name || "deck").replace(/\s+/g, "-").toLowerCase()}.json`, deck);
      setStatus("Deck exported.", false);
    });

    document.getElementById("deck-import-btn").addEventListener("click", async () => {
      const raw = ((document.getElementById("deck-import-text") || {}).value || "").trim();
      if (!raw) {
        setStatus("Paste JSON into the import box.", true);
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        const deck = parsed.deck || parsed;
        await writeDeckToForm(deck);
        setStatus("Deck imported into builder.", false);
      } catch (err) {
        setStatus(err.message || "Invalid JSON.", true);
      }
    });

    document.getElementById("meta-load-btn").addEventListener("click", async () => {
      try {
        await loadMetaDecks();
        setStatus(`Loaded ${state.metaDecks.length} deck search results.`, false);
      } catch (err) {
        setStatus(err.message || "Could not load deck search results.", true);
      }
    });

    const metaSearchInput = document.getElementById("meta-search");
    if (metaSearchInput) {
      metaSearchInput.addEventListener("keydown", async (ev) => {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        try {
          await loadMetaDecks();
          setStatus(`Loaded ${state.metaDecks.length} deck search results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load deck search results.", true);
        }
      });
    }

    const metaSortSelect = document.getElementById("meta-sort-by");
    if (metaSortSelect) {
      metaSortSelect.addEventListener("change", async () => {
        try {
          await loadMetaDecks();
          setStatus(`Loaded ${state.metaDecks.length} deck search results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load deck search results.", true);
        }
      });
    }

    let mainDeckRelayoutRaf = 0;
    const scheduleMainDeckRelayout = () => {
      if (mainDeckRelayoutRaf) cancelAnimationFrame(mainDeckRelayoutRaf);
      mainDeckRelayoutRaf = requestAnimationFrame(() => {
        mainDeckRelayoutRaf = 0;
        renderMainDeckList();
      });
    };
    const mainDeckList = document.getElementById("main-deck-list");
    if (mainDeckList && typeof window.ResizeObserver === "function") {
      let observedWidth = Math.round(mainDeckList.clientWidth);
      const observer = new ResizeObserver((entries) => {
        const entry = entries && entries.length ? entries[0] : null;
        const nextWidth = Math.round(entry && entry.contentRect ? entry.contentRect.width : mainDeckList.clientWidth);
        if (!nextWidth || nextWidth === observedWidth) return;
        observedWidth = nextWidth;
        scheduleMainDeckRelayout();
      });
      observer.observe(mainDeckList);
    }

    window.addEventListener("scroll", hidePreview, true);
    window.addEventListener("resize", () => {
      hidePreview();
      scheduleMainDeckRelayout();
    });
    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        closePicker();
        closeReplacementModal();
        closeMainCardModal();
        hidePreview();
      }
    });
  }

  async function init() {
    closePicker();
    closeReplacementModal();
    closeMainCardModal();
    bindEvents();
    applyWorkspaceTab();
    applyDeckSectionFocus();
    try {
      await loadCardCatalog();
      await refreshEligibility(state.deck.legendTitle, { applyRecommended: false, validate: false });
      renderDeckWorkbench();
      await loadCollection();
      await loadLibrary();
      await loadMetaDecks();
      scheduleValidation(true);
      setStatus("Ready", false);
    } catch (err) {
      setStatus(err.message || "Startup load failed.", true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    void init();
  }
})();
