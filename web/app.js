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
  function runtimeConfig() {
    return (typeof window !== "undefined" && window.__RIFTBOUND_CONFIG__) || {};
  }

  const state = {
    auth: {
      client: null,
      session: null,
      me: null,
      featureFlags: {
        autoBuilderEnabled: true,
        modelObservationEnabled: false,
        communityGalleryEnabled: true
      },
      status: "signed-out",
      message: ""
    },
    collection: {},
    collectionOwnedByKey: {},
    collectionAvailableByKey: {},
    collectionInUseByKey: {},
    library: [],
    metaDecks: [],
    communityDecks: [],
    metaStatus: null,
    formats: [],
    cards: [],
    cardsByTitle: {},
    cardsByKey: {},
    editor: {
      deckId: "",
      bucket: "saved",
      visibility: "private",
      publishedAt: "",
      ownerDisplayName: "",
      lastSavedFingerprint: ""
    },
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
      allowedMainCardTypes: ["Unit", "Gear", "Spell"],
      sideboardMax: 8,
      allowedSideboardCardTypes: ["Unit", "Gear", "Spell"]
    },
    picker: {
      kind: "",
      battlefieldIndex: 0
    },
    ui: {
      workspaceTab: "deck",
      discoverTab: "meta",
      replacementCardTitle: "",
      deckReservationMode: "",
      collectionEditMode: false,
      collectionFiltersOpen: false,
      collectionSearch: "",
      libraryDragDeckId: "",
      libraryDragSourceBucket: "",
      libraryExpandedDeckId: "",
      metaDetailIndex: -1,
      metaDetailSource: "meta",
      loadedWorkspaces: {
        core: false,
        library: false,
        deck: false,
        collection: false,
        discover: false,
        autoBuilder: false,
        modelObservation: false,
        wizard: false
      },
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
    autoBuilder: {
      status: null,
      recommendations: [],
      selectedIndex: 0,
      rankingMode: "collection",
      strategyMode: "hybrid",
      legendTitle: "",
      chosenChampionTitle: "",
      onlyBuildable: false,
      eligibility: {
        legends: [],
        champions: []
      },
      completionResult: null,
      loading: false
    },
    modelObservation: {
      overview: null,
      training: null,
      models: [],
      observation: null,
      selectedModelId: "",
      selectedGraphNodeId: "",
      graphFocus: "all",
      graphSearch: "",
      graphViewport: {
        x: 0,
        y: 0,
        scale: 1,
        initialized: false
      },
      graphNodePositions: {},
      graphPinnedNodeIds: {},
      loading: false,
      pollTimer: 0,
      hydrated: false,
      form: {
        label: "",
        epochs: 12,
      }
    },
    lastValidation: null,
    validateTimer: null,
    wizard: {
      step: "start",
      format: "constructed",
      collectionAgnostic: false,
      transientCollection: {},
      eligibility: null,
      deck: {
        name: "Guided Deck",
        source: "wizard",
        format: "constructed",
        legendTitle: "",
        chosenChampionTitle: "",
        main: {},
        runes: {},
        battlefields: ["", "", ""],
        sideboard: {}
      },
      targetDeck: null,
      optimalTargetDeck: null,
      recommendations: [],
      activeReplacementCard: null,
      activeReplacementOptions: [],
      activeReplacementLoading: false,
      activeReplacementNotice: "",
      physicalChecklistMode: false,
      decisions: [],
      searchQuery: "",
      iteration: 0,
      iterationHistory: [],
      savedRecommendations: [],
      lastRefinement: null,
      completeData: null
    }
  };
  let activeModelGraphRuntime = null;
  let scheduledMetaRefreshTimer = 0;

  function currentAccessToken() {
    return String((state.auth.session && state.auth.session.access_token) || "").trim();
  }

  async function api(path, options) {
    const init = options || {};
    const headers = { ...(init.headers || {}) };
    const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
    const body = init.body == null ? undefined : isFormData ? init.body : JSON.stringify(init.body);
    if (body && !isFormData) headers["Content-Type"] = headers["Content-Type"] || "application/json";
    const token = currentAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const config = runtimeConfig();
    const res = await fetch(`${String(config.apiBase || "").trim()}${path}`, {
      headers: Object.keys(headers).length ? headers : undefined,
      ...init,
      body
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = payload && payload.detail ? payload.detail : res.statusText;
      if (res.status === 401 && state.auth.status === "authenticated") {
        await signOut("Session expired. Sign in again.");
        setAuthMessage("Session expired. Sign in again.", true);
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function authConfigured() {
    const config = runtimeConfig();
    return Boolean(config.supabaseUrl && config.supabaseAnonKey && window.supabase && window.supabase.createClient);
  }

  function authClient() {
    if (!state.auth.client && authConfigured()) {
      const config = runtimeConfig();
      state.auth.client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
    }
    return state.auth.client;
  }

  function requireAuthClient() {
    const client = authClient();
    if (client && client.auth) return client;
    state.auth.status = "configuration-error";
    state.auth.message = "Supabase auth is not configured for this environment. Check RB_SUPABASE_URL and RB_SUPABASE_ANON_KEY, then restart the server.";
    renderAuthShell();
    throw new Error(state.auth.message);
  }

  function setAuthMessage(text, error) {
    state.auth.message = String(text || "").trim();
    const root = document.getElementById("auth-status");
    if (!root) return;
    root.textContent = state.auth.message || (error ? "Sign-in failed." : "Awaiting sign-in.");
    root.style.color = error ? "#ffd6d8" : "#f4dfb8";
  }

  function renderFeatureFlags() {
    const flags = state.auth.featureFlags || {};
    const autoBuilderEnabled = Boolean(flags.autoBuilderEnabled);
    const modelObservationEnabled = Boolean(flags.modelObservationEnabled);
    const communityEnabled = flags.communityGalleryEnabled !== false;
    const autoBuilderTab = document.getElementById("workspace-tab-auto-builder");
    const communityTab = document.getElementById("discover-community-tab");
    if (autoBuilderTab) autoBuilderTab.hidden = !autoBuilderEnabled;
    if (communityTab) communityTab.hidden = !communityEnabled;
    if (state.auth.status === "authenticated") {
      if (!autoBuilderEnabled && state.ui.workspaceTab === "auto-builder") {
        state.ui.workspaceTab = "deck";
      }
      if (!communityEnabled && state.ui.discoverTab === "community") {
        state.ui.discoverTab = "meta";
      }
      if (!modelObservationEnabled && state.ui.workspaceTab === "model-observation") {
        state.ui.workspaceTab = "deck";
      }
    }
  }

  function renderAccountShell() {
    const me = state.auth.me || {};
    const accountShell = document.getElementById("account-shell");
    const displayName = document.getElementById("account-display-name");
    const email = document.getElementById("account-email");
    const roleChip = document.getElementById("account-role-chip");
    const modelObservationBtn = document.getElementById("account-model-observation-btn");
    const metaRefreshBtn = document.getElementById("meta-refresh-btn");
    if (accountShell) accountShell.hidden = state.auth.status !== "authenticated";
    if (displayName) displayName.textContent = String((me && me.displayName) || "Beta User");
    if (email) email.textContent = String((me && me.email) || "");
    const isAdmin = String((me && me.role) || "").trim().toLowerCase() === "admin";
    if (roleChip) roleChip.hidden = !isAdmin;
    if (modelObservationBtn) modelObservationBtn.hidden = !isAdmin;
    const sidebarModelBtn = document.getElementById("sidebar-nav-model-observation-btn");
    if (sidebarModelBtn) sidebarModelBtn.hidden = !isAdmin;
    if (metaRefreshBtn) metaRefreshBtn.hidden = !isAdmin || state.ui.discoverTab !== "meta";
  }

  function isSetupRoute() {
    return /^#\/setup$/i.test(String(window.location && window.location.hash || "").trim());
  }

  function renderSetupGateView(showComplete, statusText, statusError) {
    const intro = document.getElementById("account-setup-intro");
    const complete = document.getElementById("account-setup-complete");
    const statusEl = document.getElementById("account-setup-status");
    if (intro) intro.hidden = !!showComplete;
    if (complete) complete.hidden = !showComplete;
    if (statusEl) {
      statusEl.hidden = !statusText;
      statusEl.textContent = statusText || "";
      statusEl.style.color = statusError ? "#ffd6d8" : "#f4dfb8";
    }
  }

  function renderAuthShell() {
    const authGate = document.getElementById("auth-gate");
    const setupGate = document.getElementById("account-setup-gate");
    const appShell = document.getElementById("app-shell");
    const authenticated = state.auth.status === "authenticated";
    const onSetup = isSetupRoute();

    if (authenticated) {
      if (authGate) authGate.hidden = true;
      renderAccountShell();
      renderFeatureFlags();
      if (onSetup) {
        if (setupGate) {
          setupGate.hidden = false;
          renderSetupGateView(true, "", false);
        }
        if (appShell) appShell.hidden = true;
      } else {
        if (setupGate) setupGate.hidden = true;
        if (appShell) appShell.hidden = false;
      }
      return;
    }

    if (appShell) appShell.hidden = true;
    if (onSetup) {
      if (authGate) authGate.hidden = true;
      if (setupGate) setupGate.hidden = false;
      const errMsg = (state.auth.message && state.auth.message.trim()) ? state.auth.message.trim() : "";
      renderSetupGateView(false, errMsg, !!errMsg);
    } else {
      if (authGate) authGate.hidden = false;
      if (setupGate) setupGate.hidden = true;
    }

    if (!onSetup) {
      if (state.auth.status === "configuration-error") {
        setAuthMessage("Supabase auth is not configured for this environment.", true);
        return;
      }
      setAuthMessage(state.auth.message || "Awaiting sign-in.", state.auth.status === "error");
    }
  }

  function applyMePayload(payload) {
    const body = payload && typeof payload === "object" ? payload : {};
    state.auth.me = body.user || null;
    state.auth.featureFlags = body.featureFlags || state.auth.featureFlags;
    state.auth.status = "authenticated";
    state.auth.message = "";
    renderAuthShell();
  }

  async function signOut(message) {
    const config = runtimeConfig();
    if (config.offlineMode) {
      return;
    }
    const client = authClient();
    if (client && client.auth && typeof client.auth.signOut === "function") {
      await client.auth.signOut();
    }
    if (scheduledMetaRefreshTimer) {
      clearTimeout(scheduledMetaRefreshTimer);
      scheduledMetaRefreshTimer = 0;
    }
    state.auth.session = null;
    state.auth.me = null;
    state.auth.status = "signed-out";
    state.auth.message = String(message || "Signed out.").trim();
    state.collection = {};
    state.collectionOwnedByKey = {};
    state.collectionAvailableByKey = {};
    state.collectionInUseByKey = {};
    state.library = [];
    state.metaDecks = [];
    state.metaIncludeCollection = true;
    state.communityDecks = [];
    state.metaStatus = null;
    state.ui.loadedWorkspaces = {
      core: false,
      library: false,
      deck: false,
      collection: false,
      discover: false,
      autoBuilder: false,
      modelObservation: false
    };
    renderAuthShell();
  }

  async function bootstrapSession() {
    if (!currentAccessToken()) return false;
    try {
      const payload = await api("/api/me/bootstrap", { method: "POST" });
      applyMePayload(payload);
      return true;
    } catch (err) {
      await signOut(err.message || "Beta access is not active for this account.");
      state.auth.status = "error";
      setAuthMessage(err.message || "Beta access is not active for this account.", true);
      return false;
    }
  }

  async function initializeAuth() {
    const config = runtimeConfig();
    if (config.offlineMode) {
      state.auth.session = {
        access_token: "local-offline-token",
        user: {
          id: "local-user",
          email: "local@example.com"
        }
      };
      state.auth.status = "authenticated";
      return bootstrapSession();
    }

    if (!authConfigured()) {
      state.auth.status = "configuration-error";
      renderAuthShell();
      return false;
    }
    const client = requireAuthClient();
    const sessionResult = await client.auth.getSession();
    state.auth.session = sessionResult && sessionResult.data ? sessionResult.data.session : null;
    if (!state.auth.session) {
      state.auth.status = "signed-out";
      renderAuthShell();
      return false;
    }
    return bootstrapSession();
  }

  async function loginWithPassword(email, password) {
    const client = requireAuthClient();
    const result = await client.auth.signInWithPassword({ email, password });
    if (result.error) throw new Error(result.error.message || "Sign-in failed.");
    state.auth.session = result.data ? result.data.session : null;
    const ok = await bootstrapSession();
    if (!ok) throw new Error(state.auth.message || "Beta access is not active for this account.");
    return true;
  }

  async function sendPasswordResetEmail(email) {
    const client = requireAuthClient();
    const result = await client.auth.resetPasswordForEmail(email);
    if (result.error) throw new Error(result.error.message || "Password reset failed.");
    setAuthMessage("Password reset link sent if the account exists.", false);
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function escAttr(text) {
    return esc(text).replace(/"/g, "&quot;");
  }

  function formatMoney(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return "-";
    return `$${num.toFixed(2)}`;
  }

  function stripStarterSuffix(text) {
    let raw = String(text == null ? "" : text)
      .replace(/[\u2013\u2014]/g, "-")
      .trim();
    // First strip trailing parenthetical promo/event suffixes
    raw = raw.replace(/\s*\([^)]*\)\s*$/, "").trim();
    // Then strip trailing starter suffixes
    raw = raw.replace(/\s*[-,]\s*starter\s*$/i, "").trim();
    return raw;
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

  function truncateText(value, maxChars) {
    const text = String(value || "").trim();
    const limit = Math.max(1, Number(maxChars) || 1);
    if (text.length <= limit) return text;
    return `${text.slice(0, limit)}...`;
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

  function normalizeLibraryBucket(value) {
    return String(value || "").trim().toLowerCase() === "built" ? "built" : "saved";
  }

  const BANNED_CARDS = new Set([
    "Called Shot",
    "Draven - Vanquisher",
    "Fight or Flight",
    "Scrapheap",
    "Obelisk of Power",
    "Reaver's Row",
    "The Dreaming Tree"
  ]);

  function isDeckIllegal(deck) {
    if (!deck) return false;
    const check = (title) => {
      if (!title) return false;
      const canonical = canonicalTitle(title);
      return BANNED_CARDS.has(canonical);
    };
    if (check(deck.legendTitle)) return true;
    if (check(deck.chosenChampionTitle)) return true;
    if (deck.main && Object.keys(deck.main).some(check)) return true;
    if (deck.sideboard && Object.keys(deck.sideboard).some(check)) return true;
    if (deck.runes && Object.keys(deck.runes).some(check)) return true;
    if (deck.battlefields && deck.battlefields.some(check)) return true;
    return false;
  }


  function normalizeDeckVisibility(value) {
    return String(value || "").trim().toLowerCase() === "public" ? "public" : "private";
  }

  function currentDeckFingerprint() {
    return JSON.stringify({
      bucket: normalizeLibraryBucket(state.editor.bucket),
      visibility: normalizeDeckVisibility(state.editor.visibility),
      deck: currentDeckFromForm()
    });
  }

  function syncDeckMetaControls() {
    const bucketSelect = document.getElementById("deck-bucket-select");
    if (bucketSelect && bucketSelect.value !== normalizeLibraryBucket(state.editor.bucket)) {
      bucketSelect.value = normalizeLibraryBucket(state.editor.bucket);
    }
    const visibilitySelect = document.getElementById("deck-visibility-select");
    if (visibilitySelect && visibilitySelect.value !== normalizeDeckVisibility(state.editor.visibility)) {
      visibilitySelect.value = normalizeDeckVisibility(state.editor.visibility);
    }
  }

  function updateDeckSaveState() {
    const root = document.getElementById("deck-save-state");
    if (!root) return;
    const hasSavedFingerprint = Boolean(state.editor.lastSavedFingerprint);
    const dirty = !hasSavedFingerprint || state.editor.lastSavedFingerprint !== currentDeckFingerprint();
    root.classList.toggle("is-clean", !dirty);
    root.textContent = dirty ? "Unsaved changes" : "Saved";
  }

  function applyEditorMeta(meta) {
    const src = meta && typeof meta === "object" ? meta : {};
    state.editor.deckId = String(src.deckId || "").trim();
    state.editor.bucket = normalizeLibraryBucket(src.bucket || state.editor.bucket);
    state.editor.visibility = normalizeDeckVisibility(src.visibility || state.editor.visibility);
    state.editor.publishedAt = String(src.publishedAt || "").trim();
    state.editor.ownerDisplayName = String(src.ownerDisplayName || "").trim();
    state.ui.deckReservationMode = state.editor.bucket === "built" ? "built" : "";
    syncDeckMetaControls();
    updateDeckSaveState();
  }

  function markDeckSaved(row) {
    applyEditorMeta({
      deckId: row && row.id,
      bucket: row && row.bucket,
      visibility: row && row.visibility,
      publishedAt: row && row.publishedAt,
      ownerDisplayName: row && row.ownerDisplayName
    });
    state.editor.lastSavedFingerprint = currentDeckFingerprint();
    updateDeckSaveState();
  }

  function mainTotal() {
    return Object.values(state.deck.main || {}).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
  }

  function runeTotal() {
    return Object.values(state.deck.runes || {}).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
  }

  function sideboardTotal() {
    return Object.values(state.deck.sideboard || {}).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
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

  function currentMainDeckCopies(title) {
    const key = canonicalTitle(title);
    if (!key) return 0;
    return Object.entries(state.deck.main || {}).reduce((sum, [rawTitle, rawQty]) => {
      if (canonicalTitle(rawTitle) !== key) return sum;
      return sum + (Math.max(0, Number(rawQty) || 0));
    }, 0);
  }

  function collectionCoverageCopies(title) {
    const ownedTotal = collectionOwnedCopies(title);
    let available = collectionAvailableCopies(title);
    if (String(state.ui.deckReservationMode || "") === "built") {
      available += currentMainDeckCopies(title);
    }
    return Math.max(0, Math.min(ownedTotal, available));
  }

  function summarizeMainDeckCollectionCoverage() {
    const missingByTitle = {};
    let ownedTotal = 0;
    Object.entries(state.deck.main || {}).forEach(([rawTitle, rawQty]) => {
      const title = canonicalTitle(rawTitle);
      const required = Math.max(0, Number(rawQty) || 0);
      if (!title || required <= 0) return;
      const owned = collectionCoverageCopies(title);
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

  let collectionPendingPatch = {};
  let collectionSaveTimer = null;
  let collectionSaveInFlight = null;

  function applyCollectionQuantityLocal(title, quantity) {
    const clean = canonicalTitle(title) || String(title || "").trim();
    if (!clean) return "";
    const nextQty = Math.max(0, Number(quantity || 0) || 0);
    if (!state.collection || typeof state.collection !== "object") state.collection = {};
    if (nextQty <= 0) delete state.collection[clean];
    else state.collection[clean] = nextQty;
    state.collectionOwnedByKey = collectionKeyMap(state.collection);
    refreshCollectionUsageFromLibraryState();
    return clean;
  }

  async function reloadCollectionFromServer() {
    const payload = await api("/api/collection");
    renderCollection(payload);
    return payload;
  }

  async function flushCollectionPending() {
    if (collectionSaveInFlight) {
      await collectionSaveInFlight;
    }
    const pending = { ...collectionPendingPatch };
    collectionPendingPatch = {};
    const keys = Object.keys(pending);
    if (!keys.length) return;
    collectionSaveInFlight = (async () => {
      try {
        const payload = await api("/api/collection", {
          method: "PATCH",
          body: { cards: pending }
        });
        renderCollection(payload);
      } catch (err) {
        try {
          await reloadCollectionFromServer();
        } catch (_reloadErr) {
          // Keep local state if reload fails.
        }
        throw err;
      } finally {
        collectionSaveInFlight = null;
      }
    })();
    await collectionSaveInFlight;
    if (Object.keys(collectionPendingPatch).length) {
      scheduleCollectionSave();
    }
  }

  function scheduleCollectionSave() {
    if (collectionSaveTimer) clearTimeout(collectionSaveTimer);
    collectionSaveTimer = setTimeout(() => {
      collectionSaveTimer = null;
      flushCollectionPending().catch((err) => {
        const message = String((err && err.message) || err || "");
        if (/429|too many requests/i.test(message)) {
          setStatus("Collection save rate-limited. Wait a few seconds and try again.", true);
        } else {
          setStatus(message || "Collection update failed.", true);
        }
      });
    }, 400);
  }

  function queueCollectionQuantity(title, quantity) {
    const clean = applyCollectionQuantityLocal(title, quantity);
    if (!clean) return;
    collectionPendingPatch[clean] = Math.max(0, Number(quantity || 0) || 0);
    rerenderCollectionFromState();
    scheduleCollectionSave();
  }

  async function setCollectionQuantity(title, quantity) {
    queueCollectionQuantity(title, quantity);
    if (collectionSaveTimer) {
      clearTimeout(collectionSaveTimer);
      collectionSaveTimer = null;
    }
    await flushCollectionPending();
  }

  async function adjustCollectionQuantity(title, delta) {
    if (!title || !delta) return;
    const current = collectionOwnedCopies(title);
    const next = Math.max(0, current + (Number(delta) || 0));
    if (next === current) return;
    queueCollectionQuantity(title, next);
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

  function deckRequirementMap(deck) {
    const normalized = normalizeDeckPayload(deck || {});
    const requirements = {};

    const add = (title, qty) => {
      const clean = canonicalTitle(title);
      const count = Math.max(0, Number(qty) || 0);
      if (!clean || count <= 0) return;
      requirements[clean] = (requirements[clean] || 0) + count;
    };

    Object.entries(normalized.main || {}).forEach(([title, qty]) => add(title, qty));
    Object.entries(normalized.runes || {}).forEach(([title, qty]) => add(title, qty));
    Object.entries(normalized.sideboard || {}).forEach(([title, qty]) => add(title, qty));
    (normalized.battlefields || []).forEach((title) => add(title, 1));
    if (normalized.legendTitle) add(normalized.legendTitle, 1);
    if (normalized.chosenChampionTitle) {
      requirements[normalized.chosenChampionTitle] = Math.max(1, Number(requirements[normalized.chosenChampionTitle] || 0) || 0);
    }
    return requirements;
  }

  function sortLibraryRows() {
    state.library = (state.library || []).slice().sort((left, right) => {
      const lValue = Date.parse(String((left && left.updatedAt) || "")) || 0;
      const rValue = Date.parse(String((right && right.updatedAt) || "")) || 0;
      if (rValue !== lValue) return rValue - lValue;
      return String((left && left.name) || "").localeCompare(String((right && right.name) || ""));
    });
  }

  function upsertLibraryRow(row) {
    const next = row && typeof row === "object" ? row : null;
    if (!next || !next.id) return null;
    const rows = Array.isArray(state.library) ? state.library.slice() : [];
    const idx = rows.findIndex((entry) => String((entry && entry.id) || "") === String(next.id));
    if (idx >= 0) rows[idx] = next;
    else rows.push(next);
    state.library = rows;
    sortLibraryRows();
    return next;
  }

  function refreshCollectionUsageFromLibraryState() {
    const owned = state.collection && typeof state.collection === "object" ? state.collection : {};
    if (!Object.keys(owned).length) return;

    const inUseByKey = {};
    (state.library || []).forEach((row) => {
      if (normalizeLibraryBucket(row && row.bucket) !== "built") return;
      const requirements = deckRequirementMap(row && row.deck);
      Object.entries(requirements).forEach(([title, qty]) => {
        const key = normalizeCardKey(title);
        if (!key) return;
        inUseByKey[key] = (inUseByKey[key] || 0) + Math.max(0, Number(qty) || 0);
      });
    });

    const inUseCards = {};
    const availableCards = {};
    Object.keys(owned).forEach((title) => {
      const clean = canonicalTitle(title) || String(title || "").trim();
      const ownedQty = Math.max(0, Number(owned[title] || 0) || 0);
      if (!clean || ownedQty <= 0) return;
      const key = normalizeCardKey(clean);
      const usedQty = Math.min(ownedQty, Math.max(0, Number((key && inUseByKey[key]) || 0) || 0));
      const availableQty = Math.max(0, ownedQty - usedQty);
      if (usedQty > 0) inUseCards[clean] = usedQty;
      if (availableQty > 0) availableCards[clean] = availableQty;
    });

    state.collectionOwnedByKey = collectionKeyMap(owned);
    state.collectionInUseByKey = collectionKeyMap(inUseCards);
    state.collectionAvailableByKey = collectionKeyMap(availableCards);

    if (state.ui.loadedWorkspaces && state.ui.loadedWorkspaces.collection) {
      rerenderCollectionFromState();
    }
    if (state.analysis.active) {
      refreshActiveAnalysisView();
      if (state.ui.replacementCardTitle) {
        renderReplacementModal();
      }
    }
    renderDeckWorkbench();
  }

  function scheduleMetaDeckRefresh() {
    if (!state.ui.loadedWorkspaces || !state.ui.loadedWorkspaces.discover) return;
    if (String(state.ui.discoverTab || "meta") !== "meta") return;
    if (scheduledMetaRefreshTimer) {
      clearTimeout(scheduledMetaRefreshTimer);
    }
    scheduledMetaRefreshTimer = window.setTimeout(() => {
      scheduledMetaRefreshTimer = 0;
      loadMetaDecks({ preserveExisting: true, refreshStatus: false }).catch(() => {
        // Keep the local deck move instant even if meta refresh fails.
      });
    }, 250);
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

  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  let _statusTimer;
  function setStatus(text, error) {
    const el = document.getElementById("app-status");
    if (!el) return;
    clearTimeout(_statusTimer);
    el.textContent = text;
    el.style.color = error ? "#ffd6d8" : "#d9ffeb";
    _statusTimer = setTimeout(() => {
      el.textContent = "Ready";
      el.style.color = "#d9ffeb";
    }, error ? 6000 : 3000);
  }

  async function withBusy(btn, busyLabel, fn) {
    if (!btn || btn.disabled) return;
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.classList.add("is-loading");
    if (busyLabel) btn.textContent = busyLabel;
    try {
      return await fn();
    } finally {
      btn.disabled = false;
      btn.classList.remove("is-loading");
      if (busyLabel) btn.innerHTML = origHtml;
    }
  }

  function showConfirmModal({
    title = "Confirm",
    body = "",
    requireInput = false,
    inputPlaceholder = "",
    inputDefault = "",
    inputMatch = null,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    onConfirm = () => {},
    onCancel = () => {}
  } = {}) {
    const modal = document.getElementById("confirm-modal");
    const titleEl = document.getElementById("confirm-modal-title");
    const bodyEl = document.getElementById("confirm-modal-body");
    const inputEl = document.getElementById("confirm-modal-input");
    const okBtn = document.getElementById("confirm-modal-ok");
    const cancelBtn = document.getElementById("confirm-modal-cancel");
    if (!modal) return;

    titleEl.textContent = title;
    bodyEl.textContent = body;
    okBtn.textContent = confirmLabel;
    cancelBtn.textContent = cancelLabel;

    if (requireInput) {
      inputEl.hidden = false;
      inputEl.placeholder = inputPlaceholder;
      inputEl.value = inputDefault || "";
      if (inputMatch) {
        okBtn.disabled = inputEl.value !== inputMatch;
        inputEl.oninput = () => { okBtn.disabled = inputEl.value !== inputMatch; };
      } else {
        okBtn.disabled = false;
        inputEl.oninput = null;
      }
    } else {
      inputEl.hidden = true;
      inputEl.oninput = null;
      okBtn.disabled = false;
    }

    modal.hidden = false;
    if (requireInput) window.setTimeout(() => inputEl.focus(), 0);

    function cleanup() {
      modal.hidden = true;
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      inputEl.oninput = null;
    }

    okBtn.onclick = () => {
      cleanup();
      onConfirm(requireInput ? inputEl.value : null);
    };
    cancelBtn.onclick = () => {
      cleanup();
      onCancel();
    };
    modal.onclick = (e) => {
      if (e.target === modal) {
        cleanup();
        onCancel();
      }
    };
  }

  function confirmModal(options) {
    return new Promise((resolve) => {
      showConfirmModal({
        ...options,
        onConfirm: (value) => resolve({ confirmed: true, value }),
        onCancel: () => resolve({ confirmed: false, value: null })
      });
    });
  }

  function normalizeWorkspacePath(pathname) {
    const raw = String(pathname || "").trim().toLowerCase();
    let decoded = raw;
    try {
      decoded = decodeURIComponent(raw);
    } catch (_err) {
      decoded = raw.replace(/%25/g, "%");
    }
    return decoded.replace(/[^a-z]+/g, "");
  }

  function isModelObservationPath(pathname) {
    return normalizeWorkspacePath(pathname).includes("modelobservation");
  }

  function bootWorkspaceHint() {
    if (typeof window === "undefined") return "";
    const hinted = String(window.__RIFTBOUND_BOOT_WORKSPACE || "").trim().toLowerCase();
    if (hinted === "model-observation") return "model-observation";
    try {
      const params = new URLSearchParams(String(window.location && window.location.search) || "");
      const queryValue = String(params.get("workspace") || "").trim().toLowerCase();
      if (queryValue === "model-observation") return "model-observation";
    } catch (_err) {
      // ignore malformed query strings
    }
    const hash = String((window.location && window.location.hash) || "").trim().toLowerCase().replace(/^#/, "");
    if (hash === "model-observation") return "model-observation";
    return "";
  }

  function syncWorkspaceRoute() {
    if (!window || !window.history || typeof window.history.replaceState !== "function") return;
    const active = String((state.ui && state.ui.workspaceTab) || "deck").trim();
    const current = String((window.location && window.location.pathname) || "/").trim() || "/";
    if (active === "model-observation") {
      if (!isModelObservationPath(current)) {
        window.history.replaceState({}, "", "/model-observation");
      }
      return;
    }
    if (isModelObservationPath(current)) {
      window.history.replaceState({}, "", "/");
    }
  }

  function applyWorkspaceTab() {
    const raw = String((state.ui && state.ui.workspaceTab) || "deck").trim();
    const active = raw === "collection" || raw === "auto-builder" || raw === "discover" || raw === "model-observation" || raw === "wizard" ? raw : "deck";
    state.ui.workspaceTab = active;

    const collectionPanel = document.getElementById("collection-panel");
    const deckPanel = document.getElementById("deck-panel");
    const autoBuilderPanel = document.getElementById("auto-builder-panel");
    const modelObservationPanel = document.getElementById("model-observation-panel");
    const wizardPanel = document.getElementById("wizard-panel");
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
    if (autoBuilderPanel) {
      const on = active === "auto-builder";
      autoBuilderPanel.classList.toggle("is-active", on);
      autoBuilderPanel.hidden = !on;
    }
    if (modelObservationPanel) {
      const on = active === "model-observation";
      modelObservationPanel.classList.toggle("is-active", on);
      modelObservationPanel.hidden = !on;
    }
    if (wizardPanel) {
      const on = active === "wizard";
      wizardPanel.classList.toggle("is-active", on);
      wizardPanel.hidden = !on;
    }

    document.body.classList.toggle("workspace-auto-builder-active", active === "auto-builder");
    document.body.classList.toggle("workspace-discover-active", active === "discover");
    document.body.classList.toggle("workspace-model-observation-active", active === "model-observation");
    document.body.classList.toggle("workspace-wizard-active", active === "wizard");

    // Inspector panel is discover-only — hide/show via hidden attribute (overrides all CSS specificity)
    const inspectorPanel = document.getElementById("inspector-panel");
    const workspacePanel = document.getElementById("workspace-panel");
    if (inspectorPanel) inspectorPanel.hidden = active !== "discover";
    if (workspacePanel) workspacePanel.hidden = active === "discover";

    Array.from(document.querySelectorAll("[data-workspace-tab]")).forEach((btn) => {
      const target = String(btn.getAttribute("data-workspace-tab") || "").trim();
      const on = target === active;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.setAttribute("tabindex", on ? "0" : "-1");
    });
    syncWorkspaceRoute();
    if (active === "wizard") {
      renderWizard();
    }
  }

  function applyDiscoverTab() {
    const tab = String((state.ui && state.ui.discoverTab) || "meta").trim() === "community" ? "community" : "meta";
    state.ui.discoverTab = tab;
    const metaList = document.getElementById("meta-list");
    const communityList = document.getElementById("community-list");
    const freshness = document.getElementById("meta-freshness");
    const sortSelect = document.getElementById("meta-sort-by");
    const communitySortSelect = document.getElementById("community-sort-by");
    const refreshBtn = document.getElementById("meta-refresh-btn");
    const includeCollectionLabel = document.getElementById("meta-include-collection-label");
    Array.from(document.querySelectorAll("[data-discover-tab]")).forEach((btn) => {
      const on = String(btn.getAttribute("data-discover-tab") || "") === tab;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    if (metaList) metaList.hidden = tab !== "meta";
    if (communityList) communityList.hidden = tab !== "community";
    if (sortSelect) sortSelect.hidden = tab !== "meta";
    if (communitySortSelect) communitySortSelect.hidden = tab !== "community";
    if (refreshBtn) refreshBtn.hidden = tab !== "meta";
    if (freshness) freshness.hidden = tab !== "meta";
    if (includeCollectionLabel) includeCollectionLabel.hidden = tab !== "meta";
    renderAccountShell();
  }

  function setWorkspaceTab(nextTab) {
    const raw = String(nextTab || "").trim();
    if (raw === "collection" || raw === "auto-builder" || raw === "discover" || raw === "model-observation" || raw === "wizard") {
      state.ui.workspaceTab = raw;
    } else {
      state.ui.workspaceTab = "deck";
    }
    applyWorkspaceTab();
    applyDiscoverTab();
    void ensureWorkspaceLoaded(state.ui.workspaceTab).catch((err) => {
      setStatus(err.message || "Could not load workspace.", true);
    });
  }

  function setDiscoverTab(nextTab) {
    state.ui.discoverTab = String(nextTab || "").trim() === "community" ? "community" : "meta";
    applyDiscoverTab();
    if (state.ui.workspaceTab === "discover") {
      void ensureWorkspaceLoaded("discover").catch((err) => {
        setStatus(err.message || "Could not load discover results.", true);
      });
    }
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
    const disablePreview = Boolean(opts.disablePreview);
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
    const previewAttrs = disablePreview
      ? ""
      : ` data-preview-title="${escAttr(title)}"` +
        ` data-preview-image="${escAttr(resolvedImage)}"` +
        ` data-preview-meta="${escAttr(meta)}"` +
        ` data-preview-stats="${escAttr(stats)}"` +
        ` data-preview-fallback="${escAttr(fallback)}"` +
        ` data-preview-back="${escAttr(backImage || CARD_BACK_DEFAULT)}"`;
    return (
      `<article class="card-tile ${esc(extraClass)}${shelfOnly ? " shelf-card" : ""}${foil ? " is-foil" : ""}"` +
      ` style="--card-tilt:${escAttr(cardTiltFor(title))};"` +
      previewAttrs +
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
    const estimatedCompletionCost = analysis.estimated_completion_cost;
    const winConditionLabel = String(analysis.winConditionLabel || analysis.win_condition_label || "").trim();
    const missingCardsPriced = Math.max(0, Number(analysis.missing_cards_priced || 0) || 0);
    const missingCardsUnpriced = Math.max(0, Number(analysis.missing_cards_unpriced || 0) || 0);
    const missingUniqueCards = Math.max(0, Number(analysis.missing_unique_cards || 0) || 0);
    const completionCostText =
      estimatedCompletionCost == null ? "N/A" : formatMoney(estimatedCompletionCost);
    const coverageText =
      missingUniqueCards <= 0
        ? "0 priced / 0 unpriced"
        : `${missingCardsPriced} priced / ${missingCardsUnpriced} unpriced`;
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
        const unitPrice = row.estimated_unit_price == null ? null : Number(row.estimated_unit_price);
        const lineCost = row.estimated_missing_cost == null ? null : Number(row.estimated_missing_cost);
        const priceText =
          lineCost == null || !Number.isFinite(lineCost)
            ? "est N/A"
            : `est $${lineCost.toFixed(2)}${unitPrice != null && Number.isFinite(unitPrice) ? ` ($${unitPrice.toFixed(2)} ea)` : ""}`;
        const tcgplayerUrl = String(row.tcgplayer_url || "").trim();
        const buyLink = tcgplayerUrl
          ? `<a class="analysis-buy-link" href="${escAttr(tcgplayerUrl)}" target="_blank" rel="noopener noreferrer">Buy on TCGplayer</a>`
          : "";
        const options = replacementByCard[key] || [];
        const picks = options
          .slice(0, 3)
          .map((opt) => {
            const reason = String(opt.reason || "").trim();
            const source = String(opt.source || "").trim() || "heuristic";
            return `${esc(opt.card)} (${esc(source)} | score ${esc(opt.score)} | avail ${esc(opt.available)}${reason ? ` | ${esc(reason)}` : ""})`;
          })
          .join(" | ");
        const suggestion = picks ? `<div class="ok"><small>Replacements: ${picks}</small></div>` : "";
        return (
          `<div class="warn">${esc(row.card)}: need ${esc(row.required)} / owned ${esc(row.owned)} / missing ${esc(row.missing)} | ${esc(priceText)}</div>` +
          (buyLink ? `<div class="ok"><small>${buyLink}</small></div>` : "") +
          suggestion
        );
      })
      .join("");
    root.innerHTML =
      `<div><strong>Completion:</strong> ${esc(analysis.completion_pct)}% | ` +
      `<strong>Buildable:</strong> ${analysis.is_buildable ? '<span class="ok">Yes</span>' : '<span class="err">No</span>'}</div>` +
      (winConditionLabel ? `<div><strong>Win Condition:</strong> ${esc(winConditionLabel)}</div>` : "") +
      `<div><strong>Estimated Completion Cost:</strong> ${esc(completionCostText)} | <strong>Pricing Coverage:</strong> ${esc(coverageText)}</div>` +
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
    _previewNextX = clientX;
    _previewNextY = clientY;
    if (!_previewRafPending) {
      _previewRafPending = true;
      requestAnimationFrame(_commitPreviewPosition);
    }
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

  function closeDeckImportModal() {
    const modal = document.getElementById("deck-import-modal");
    if (modal) modal.hidden = true;
  }

  function openDeckImportModal() {
    const modal = document.getElementById("deck-import-modal");
    const input = document.getElementById("deck-import-text");
    if (!modal || !input) return;
    modal.hidden = false;
    input.focus();
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
    _previewDims = null; // invalidate cached dims — content changed, size may differ
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
      }, { passive: true });
      tile.addEventListener("mousemove", (ev) => {
        movePreview(ev.clientX, ev.clientY);
      }, { passive: true });
      tile.addEventListener("mouseleave", () => {
        hidePreview();
      }, { passive: true });
      // Touch: show preview centered on tile (tablet/phone)
      tile.addEventListener("touchstart", (ev) => {
        const touch = ev.touches[0];
        if (touch) {
          const rect = tile.getBoundingClientRect();
          showPreviewForTile(tile, rect.left + rect.width / 2, rect.top + rect.height / 2);
        }
      }, { passive: true });
      tile.addEventListener("touchend", () => {
        hidePreview();
      }, { passive: true });
      tile.addEventListener("touchcancel", () => {
        hidePreview();
      }, { passive: true });
    });
  }

  const foilMotionStates = new Map();
  const foilActiveStates = new Set();
  let foilMotionRaf = 0;

  // Cached matchMedia query — avoids re-creating on every frame / bindFoilInteractions call.
  const _reduceMotionMq = typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;

  // RAF-throttled preview positioning state.
  let _previewRafPending = false;
  let _previewNextX = 0;
  let _previewNextY = 0;
  let _previewDims = null; // { width, height } — cached when preview is shown

  function _commitPreviewPosition() {
    _previewRafPending = false;
    const preview = document.getElementById("card-preview");
    if (!preview || preview.hidden) return;
    const dims = _previewDims || (_previewDims = { width: preview.offsetWidth, height: preview.offsetHeight });
    const offset = 16;
    let left = _previewNextX + offset;
    let top = _previewNextY + offset;
    if (left + dims.width > window.innerWidth - 10) left = _previewNextX - dims.width - offset;
    if (top + dims.height > window.innerHeight - 10) top = _previewNextY - dims.height - offset;
    preview.style.left = `${clamp(left, 8, Math.max(8, window.innerWidth - dims.width - 8))}px`;
    preview.style.top = `${clamp(top, 8, Math.max(8, window.innerHeight - dims.height - 8))}px`;
  }

  function runFoilMotionFrame(time) {
    const reduceMotion = _reduceMotionMq ? _reduceMotionMq.matches : false;
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
    const reduceMotion = _reduceMotionMq ? _reduceMotionMq.matches : false;
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

      // Cache the bounding rect per-element to avoid forced layout on every pointermove.
      let _foilRect = null;
      const setTargetFromPointer = (ev) => {
        if (!_foilRect || !_foilRect.width) return;
        state.targetX = clamp(((ev.clientX - _foilRect.left) / _foilRect.width) * 100, 0, 100);
        state.targetY = clamp(((ev.clientY - _foilRect.top) / _foilRect.height) * 100, 0, 100);
      };

      art.addEventListener("pointerenter", (ev) => {
        _foilRect = art.getBoundingClientRect(); // read once on enter
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
      }, { passive: true });

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
      }, { passive: true });

      const reset = () => {
        _foilRect = null;
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

      art.addEventListener("pointerleave", reset, { passive: true });
      art.addEventListener("pointercancel", reset, { passive: true });
      art.addEventListener("pointerup", reset, { passive: true });
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
        btn.addEventListener("click", () => {
          const title = btn.getAttribute("data-collection-inc") || "";
          adjustCollectionQuantity(title, 1);
          setStatus("Saving collection…", false);
        });
      });
      Array.from(list.querySelectorAll("[data-collection-dec]")).forEach((btn) => {
        btn.addEventListener("click", () => {
          const title = btn.getAttribute("data-collection-dec") || "";
          adjustCollectionQuantity(title, -1);
          setStatus("Saving collection…", false);
        });
      });
    }

    if (!opts.uiOnly) {
      if (state.analysis.active) {
        refreshActiveAnalysisView();
        if (state.ui.replacementCardTitle) {
          renderReplacementModal();
        }
      }
      renderDeckWorkbench();
    }
  }

  function startLibraryDrag(deckId, sourceBucket) {
    const id = String(deckId || "");
    if (!id) return;
    state.ui.libraryDragDeckId = id;
    state.ui.libraryDragSourceBucket = String(sourceBucket || "").trim().toLowerCase() === "built" ? "built" : "saved";
  }

  function stopLibraryDrag() {
    state.ui.libraryDragDeckId = "";
    state.ui.libraryDragSourceBucket = "";
    const built = document.getElementById("library-built-gallery");
    const saved = document.getElementById("library-saved-gallery");
    const illegal = document.getElementById("library-illegal-gallery");
    if (built) built.classList.remove("is-drop-target");
    if (saved) saved.classList.remove("is-drop-target");
    if (illegal) illegal.classList.remove("is-drop-target");
  }

  function renderLibrary() {
    const builtGallery = document.getElementById("library-built-gallery");
    const savedGallery = document.getElementById("library-saved-gallery");
    const illegalGallery = document.getElementById("library-illegal-gallery");
    if (!builtGallery || !savedGallery) return;

    const builtRows = [];
    const savedRows = [];
    const illegalRows = [];
    (state.library || []).forEach((row) => {
      if (row && row.deck && isDeckIllegal(row.deck)) {
        illegalRows.push(row);
      } else {
        const bucket = String((row && row.bucket) || "saved").trim().toLowerCase();
        if (bucket === "built") builtRows.push(row);
        else savedRows.push(row);
      }
    });

    const bindDropTarget = (root, targetBucket) => {
      if (!root) return;
      if (root.dataset.libDropBound === targetBucket) return;
      root.dataset.libDropBound = targetBucket;
      root.addEventListener("dragover", (ev) => {
        const dragId = String(state.ui.libraryDragDeckId || "");
        const sourceBucket = String(state.ui.libraryDragSourceBucket || "");
        if (!dragId || !sourceBucket || sourceBucket === targetBucket) return;
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
        root.classList.add("is-drop-target");
      });
      root.addEventListener("dragleave", (ev) => {
        const next = ev.relatedTarget;
        if (next && root.contains(next)) return;
        root.classList.remove("is-drop-target");
      });
      root.addEventListener("drop", async (ev) => {
        const dragId = String(state.ui.libraryDragDeckId || "");
        const sourceBucket = String(state.ui.libraryDragSourceBucket || "");
        root.classList.remove("is-drop-target");
        stopLibraryDrag();
        if (!dragId || !sourceBucket || sourceBucket === targetBucket) return;
        ev.preventDefault();
        try {
          await setLibraryDeckBucket(dragId, targetBucket);
        } catch (err) {
          setStatus(err.message || "Could not move deck.", true);
        }
      });
    };

    const renderGallery = (root, rows, bucket) => {
      if (!root) return;
      if (!rows.length) {
        if (bucket === "built") {
          root.innerHTML = '<div class="card-tile"><div class="card-body"><div class="card-title">No built decks yet.</div><div class="card-subtitle">Drag saved decks here to reserve cards.</div></div></div>';
        } else if (bucket === "saved") {
          root.innerHTML = '<div class="card-tile"><div class="card-body"><div class="card-title">No saved decks yet.</div><div class="card-subtitle">Drag built decks here to release reserved cards.</div></div></div>';
        } else {
          root.innerHTML = '<div class="card-tile"><div class="card-body"><div class="card-title">No illegal decks yet.</div><div class="card-subtitle">Decks containing banned cards will appear here.</div></div></div>';
        }
        return;
      }
      root.innerHTML = rows
        .map((row) => {
          const deckId = String(row.id || "");
          const expanded = deckId && state.ui.libraryExpandedDeckId === deckId;
          const deckName = String(row.name || "Saved Deck").trim() || "Saved Deck";
          const displayName = truncateText(deckName, 20);
          const legendTitle = (row.deck && row.deck.legendTitle) || "";
          const info = lookupCard(legendTitle);
          const source = String(row.source || "").trim() || "builder";
          const visibility = normalizeDeckVisibility(row.visibility);
          const subtitle = legendTitle ? `Legend: ${legendTitle} | ${source}` : source;
          const isPublic = visibility === "public";
          const actions =
            `<button type="button" class="card-action-btn secondary" data-lib-visibility="${escAttr(row.id)}" data-lib-vis-current="${isPublic ? "public" : "private"}">${isPublic ? "Unpublish" : "Publish"}</button>` +
            `<button type="button" class="card-action-btn danger" data-lib-delete="${escAttr(row.id)}">Delete</button>`;
          return tileHtml({
            title: displayName,
            imageUrl: info && info.imageUrl ? info.imageUrl : "",
            subtitle,
            meta: subtitle,
            stats: `${bucket === "illegal" ? "Illegal" : (bucket === "built" ? "Built" : "Saved")} | ${visibility === "public" ? "Public" : "Private"}`,
            actions,
            extraClass: `library-deck-tile${expanded ? " is-expanded" : ""}`,
            extraAttrs:
              `data-lib-id="${escAttr(row.id)}"` +
              ` data-lib-bucket="${escAttr(bucket)}"` +
              ` data-lib-name-full="${escAttr(deckName)}"` +
              ` draggable="true"` +
              ` role="button"` +
              ` tabindex="0"` +
              ` aria-expanded="${expanded ? "true" : "false"}"` +
              ` aria-label="${escAttr(`Open ${row.name || "Deck"}`)}"`
          });
        })
        .join("");
      bindCardImageFallbacks(root);
      bindPreviewInteractions(root);
      bindFoilInteractions(root);

      Array.from(root.querySelectorAll("[data-lib-id]")).forEach((tile) => {
        const id = tile.getAttribute("data-lib-id") || "";
        const sourceBucket = tile.getAttribute("data-lib-bucket") || "saved";
        tile.addEventListener("click", (ev) => {
          if (ev.target && ev.target.closest && ev.target.closest("[data-lib-delete]")) return;
          if (ev.target && ev.target.closest && ev.target.closest("[data-lib-visibility]")) return;
          state.ui.libraryExpandedDeckId = state.ui.libraryExpandedDeckId === id ? "" : id;
          renderLibrary();
        });
        tile.addEventListener("dblclick", async () => {
          await openLibraryDeck(id);
        });
        tile.addEventListener("keydown", async (ev) => {
          if (ev.key !== "Enter" && ev.key !== " ") return;
          ev.preventDefault();
          await openLibraryDeck(id);
        });
        tile.addEventListener("dragstart", (ev) => {
          startLibraryDrag(id, sourceBucket);
          tile.classList.add("is-dragging");
          if (ev.dataTransfer) {
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", id);
          }
        });
        tile.addEventListener("dragend", () => {
          tile.classList.remove("is-dragging");
          stopLibraryDrag();
        });
      });

      Array.from(root.querySelectorAll("[data-lib-visibility]")).forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const id = btn.getAttribute("data-lib-visibility") || "";
          const current = btn.getAttribute("data-lib-vis-current") || "private";
          const nextVisibility = current === "public" ? "private" : "public";
          withBusy(btn, "…", async () => {
            try {
              const updated = await api(`/api/decks/library/${encodeURIComponent(id)}/visibility`, {
                method: "PUT",
                body: { visibility: nextVisibility }
              });
              const libIdx = state.library.findIndex((entry) => String((entry && entry.id) || "") === id);
              if (libIdx !== -1) state.library[libIdx] = updated;
              renderLibrary();
              setStatus(nextVisibility === "public" ? "Deck published to community." : "Deck unpublished.", false);
              refreshMetaSearchResults().catch(() => {});
            } catch (err) {
              setStatus(err.message || "Could not update visibility.", true);
            }
          });
        });
      });

      Array.from(root.querySelectorAll("[data-lib-delete]")).forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const id = btn.getAttribute("data-lib-delete") || "";
          const row = state.library.find((entry) => String(entry.id) === id);
          const label = (row && row.name) || "this deck";
          showConfirmModal({
            title: "Delete Deck",
            body: `Delete "${label}"? This cannot be undone.`,
            confirmLabel: "Delete",
            onConfirm: () => {
              // Optimistic removal — pull the deck out of state immediately.
              const prevLibrary = state.library.slice();
              state.library = state.library.filter((entry) => String((entry && entry.id) || "") !== id);
              renderLibrary();
              refreshCollectionUsageFromLibraryState();
              setStatus("Deck deleted.", false);

              // Background API call — roll back on failure.
              api(`/api/decks/library/${encodeURIComponent(id)}`, { method: "DELETE" })
                .then(() => Promise.all([loadCollection(), refreshMetaSearchResults()]))
                .catch((err) => {
                  state.library = prevLibrary;
                  renderLibrary();
                  refreshCollectionUsageFromLibraryState();
                  setStatus(err.message || "Could not delete deck.", true);
                });
            }
          });
        });
      });
    };

    renderGallery(builtGallery, builtRows, "built");
    renderGallery(savedGallery, savedRows, "saved");
    if (illegalGallery) renderGallery(illegalGallery, illegalRows, "illegal");
    bindDropTarget(builtGallery, "built");
    bindDropTarget(savedGallery, "saved");
  }

  function detailDeckRows() {
    return state.ui.metaDetailSource === "community" ? state.communityDecks : state.metaDecks;
  }

  async function useDiscoverDeck(source, idx) {
    const rows = source === "community" ? state.communityDecks : state.metaDecks;
    const row = rows[idx];
    if (!row) return;
    const name = row.deckName || row.name || (row.deck && row.deck.name) || "Deck";
    const nextDeck = { ...row.deck, name };
    await writeDeckToForm(nextDeck, { libraryBucket: "saved", visibility: "private", markSaved: false });
    setStatus(`Loaded ${source === "community" ? "community" : "meta"} deck: ${name}`, false);
  }

  async function saveDiscoverDeck(source, idx) {
    const rows = source === "community" ? state.communityDecks : state.metaDecks;
    const row = rows[idx];
    if (!row) return;
    if (source === "community" && row.id) {
      await api(`/api/decks/public/${encodeURIComponent(row.id)}/copy`, { method: "POST" });
    } else {
      await api("/api/decks/library", {
        method: "POST",
        body: {
          name: row.deckName || row.name || "Deck",
          source: row.source || (source === "community" ? "community" : "meta"),
          bucket: "saved",
          visibility: "private",
          deck: row.deck
        }
      });
    }
    await loadLibrary();
    setStatus(`Saved ${source === "community" ? "community" : "meta"} deck: ${row.deckName || row.name || "Deck"}`, false);
  }

  async function loadDeckIntoWizard(deckInput, statusName) {
    const name = statusName || (deckInput && deckInput.name) || "Deck";
    const deck = normalizeDeckPayload({
      ...(deckInput || {}),
      name,
      source: "wizard",
      format: (deckInput && deckInput.format) || state.wizard.format || "constructed"
    });
    if (!deck.legendTitle) throw new Error("This deck is missing a legend.");
    if (!deck.chosenChampionTitle) throw new Error("This deck is missing a chosen champion.");

    state.wizard.step = "deckbuilding";
    state.wizard.format = deck.format || "constructed";
    state.wizard.collectionAgnostic = false;
    state.wizard.transientCollection = {};
    state.wizard.eligibility = null;
    state.wizard.recommendations = [];
    state.wizard.activeReplacementCard = null;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementLoading = false;
    state.wizard.activeReplacementNotice = "";
    state.wizard.decisions = [];
    state.wizard.searchQuery = "";
    state.wizard.savedRecommendations = [];
    state.wizard.completeData = null;

    state.wizard.deck = deck;
    await refreshWizardEligibility();
    state.wizard.deck = capWizardDeckMainCopies(deck);
    state.wizard.targetDeck = JSON.parse(JSON.stringify(state.wizard.deck));
    state.wizard.optimalTargetDeck = JSON.parse(JSON.stringify(state.wizard.deck));
    beginWizardDeckbuildingIteration();
    loadWizardPlaylistFromStorage();

    closeMetaDetailModal();
    state.ui.workspaceTab = "wizard";
    applyWorkspaceTab();
    applyDiscoverTab();
    await ensureWorkspaceLoaded("wizard");
    renderWizard();
    setStatus(`Brought ${name} into the wizard. Mark missing cards, then refine.`, false);
  }

  async function bringDiscoverDeckToWizard(source, idx) {
    const rows = source === "community" ? state.communityDecks : state.metaDecks;
    const row = rows[idx];
    if (!row || !row.deck) throw new Error("Deck is unavailable.");

    const name = row.deckName || row.name || (row.deck && row.deck.name) || "Deck";
    await loadDeckIntoWizard(row.deck, name);
  }

  async function bringBuilderDeckToWizard() {
    const deck = currentDeckFromForm();
    await loadDeckIntoWizard(deck, deck.name || "Current Deck");
  }

  function renderMetaStatus() {
    const root = document.getElementById("meta-freshness");
    if (!root) return;
    const status = state.metaStatus;
    if (!status) {
      root.textContent = "Meta index status unavailable.";
      return;
    }
    const refreshed = status.lastRefreshedAt ? new Date(status.lastRefreshedAt).toLocaleString() : "never";
    const errorText = status.lastError ? ` | Last error: ${status.lastError}` : "";
    root.textContent = `Indexed ${status.indexedDecks || 0} / ${status.rawRows || 0} rows. Refreshed ${refreshed}.${errorText}`;
  }

  function closeMetaDetailModal() {
    state.ui.metaDetailIndex = -1;
    const modal = document.getElementById("meta-detail-modal");
    if (modal) modal.hidden = true;
  }

  function detailRowHtml(title, qty) {
    const clean = canonicalTitle(title);
    if (!clean) return "";
    const card = lookupCard(clean);
    const left = qty == null ? clean : `${qty}x ${clean}`;
    const right = card ? cardMetaLine(card) : "";
    return `<div class="meta-detail-row"><span>${esc(left)}</span><small>${esc(right)}</small></div>`;
  }

  function renderMetaDetailList(rootId, rows) {
    const root = document.getElementById(rootId);
    if (!root) return;
    if (!rows.length) {
      root.innerHTML = '<div class="meta-detail-empty">None</div>';
      return;
    }
    root.innerHTML = rows.join("");
  }

  function renderMetaDetailModal() {
    const idx = Number(state.ui.metaDetailIndex);
    const row = detailDeckRows()[idx];
    const modal = document.getElementById("meta-detail-modal");
    if (!modal) return;
    if (!row || !row.deck) {
      modal.hidden = true;
      return;
    }
    const deck = row.deck || {};
    const source = state.ui.metaDetailSource === "community" ? "community" : "meta";
    const titleEl = document.getElementById("meta-detail-title");
    const metaEl = document.getElementById("meta-detail-meta");
    const statsEl = document.getElementById("meta-detail-stats");
    if (titleEl) titleEl.textContent = row.deckName || row.name || "Deck Detail";
    if (metaEl) {
      if (source === "community") {
        const owner = String(row.ownerDisplayName || "").trim() || "Beta User";
        const legend = String(deck.legendTitle || "").trim() || "-";
        metaEl.textContent = `${owner} | ${legend} | ${String(row.visibility || "private").trim()}`;
      } else {
        const leaderInfo = lookupCard(row.leaderTitle || "");
        metaEl.textContent = `${row.source || "meta"} | ${leaderInfo ? cardMetaLine(leaderInfo) : row.leaderTitle || "-"}`;
      }
    }
    if (statsEl) {
      if (source === "community") {
        const published = row.publishedAt ? new Date(row.publishedAt).toLocaleString() : "private";
        statsEl.textContent = `Visibility ${row.visibility || "private"} | Bucket ${row.bucket || "saved"} | Published ${published}`;
      } else {
        const meta = row.metaScore == null ? "-" : Number(row.metaScore).toFixed(1);
        const competitive = row.competitiveScore == null ? "-" : Number(row.competitiveScore).toFixed(1);
        const price = row.deckPrice == null ? "-" : formatMoney(row.deckPrice);
        const winCondition = String(row.winConditionLabel || "").trim();
        if (state.metaIncludeCollection) {
          const rec = row.recommendationScore == null ? "-" : Number(row.recommendationScore).toFixed(1);
          const build = row.isBuildable == null ? "Build n/a" : row.isBuildable ? "Buildable" : `Missing ${row.missingCopies || 0}`;
          statsEl.textContent = `Recommendation ${rec} | Competitive ${competitive} | Meta ${meta} | Price ${price} | ${build}${winCondition ? ` | ${winCondition}` : ""}`;
        } else {
          statsEl.textContent = `Competitive ${competitive} | Meta ${meta} | Price ${price}${winCondition ? ` | ${winCondition}` : ""}`;
        }
      }
    }
    renderMetaDetailList("meta-detail-legend", [detailRowHtml(deck.legendTitle || "", 1)].filter(Boolean));
    renderMetaDetailList(
      "meta-detail-champion",
      [detailRowHtml(deck.chosenChampionTitle || "", (deck.main && deck.main[deck.chosenChampionTitle]) || 1)].filter(Boolean)
    );
    renderMetaDetailList(
      "meta-detail-main",
      Object.entries(deck.main || {})
        .sort((a, b) => compareTitlesByCatalogOrder(a[0], b[0]))
        .map(([title, qty]) => detailRowHtml(title, qty))
        .filter(Boolean)
    );
    renderMetaDetailList(
      "meta-detail-runes",
      Object.entries(deck.runes || {})
        .sort((a, b) => compareTitlesByCatalogOrder(a[0], b[0]))
        .map(([title, qty]) => detailRowHtml(title, qty))
        .filter(Boolean)
    );
    renderMetaDetailList(
      "meta-detail-battlefields",
      (deck.battlefields || []).map((title) => detailRowHtml(title, 1)).filter(Boolean)
    );
    renderMetaDetailList(
      "meta-detail-sideboard",
      Object.entries(deck.sideboard || {})
        .sort((a, b) => compareTitlesByCatalogOrder(a[0], b[0]))
        .map(([title, qty]) => detailRowHtml(title, qty))
        .filter(Boolean)
    );
    modal.hidden = false;
  }

  function openMetaDetailModal(idx, source) {
    state.ui.metaDetailIndex = Number(idx);
    state.ui.metaDetailSource = source === "community" ? "community" : "meta";
    renderMetaDetailModal();
  }

  function renderMeta() {
    const root = document.getElementById("meta-list");
    if (!root) return;
    if (!state.metaDecks.length) {
      root.innerHTML = '<div class="deck-card-empty">No deck results. Try a broader search or different sort.</div>';
      renderMetaStatus();
      return;
    }
    root.innerHTML = (state.metaDecks || [])
      .map((row, idx) => {
        const leaderInfo = lookupCard(row.leaderTitle || "");
        const metaText = row.metaScore == null ? "-" : Number(row.metaScore).toFixed(1);
        const competitiveText = row.competitiveScore == null ? "-" : Number(row.competitiveScore).toFixed(1);
        const priceText = row.deckPrice == null ? "-" : formatMoney(row.deckPrice);
        const winCondition = String(row.winConditionLabel || "").trim();
        const includeCollection = state.metaIncludeCollection !== false;
        let subtitleParts;
        let statsLine;
        let badgeText = "";
        if (includeCollection) {
          const recText = row.recommendationScore == null ? "-" : Number(row.recommendationScore).toFixed(1);
          const completionText = row.completionPct == null ? "-" : `${Number(row.completionPct).toFixed(1)}%`;
          const buildText =
            row.isBuildable == null ? "Build n/a" : row.isBuildable ? "Buildable" : `Missing ${row.missingCopies || 0}`;
          subtitleParts = [`Rec ${recText}`, `Competitive ${competitiveText}`, `Meta ${metaText}`, `Price ${priceText}`, buildText];
          statsLine = `Completion ${completionText}`;
          badgeText = buildText;
        } else {
          subtitleParts = [`Competitive ${competitiveText}`, `Meta ${metaText}`, `Price ${priceText}`];
          statsLine = "";
        }
        const actions =
          `<button type="button" class="card-action-btn secondary" data-meta-view="${idx}">View</button>` +
          `<button type="button" class="card-action-btn" data-meta-wizard="${idx}">Bring to Wizard</button>` +
          `<button type="button" class="card-action-btn" data-meta-save="${idx}">Save to My Decks</button>`;
        return tileHtml({
          title: row.deckName || "Deck",
          imageUrl: leaderInfo && leaderInfo.imageUrl ? leaderInfo.imageUrl : "",
          subtitle: subtitleParts.join(" | "),
          meta: `${row.source || "meta"} | ${leaderInfo ? cardMetaLine(leaderInfo) : canonicalTitle(row.leaderTitle || "")}${winCondition ? ` | ${winCondition}` : ""}`,
          stats: statsLine,
          badge: badgeText,
          badgeClass: "is-bottom-right",
          actions
        });
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-meta-view]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          openMetaDetailModal(Number(btn.getAttribute("data-meta-view")), "meta");
        } catch (err) {
          setStatus(err.message || "Could not load meta deck.", true);
        }
      });
    });
    Array.from(root.querySelectorAll("[data-meta-save]")).forEach((btn) => {
      btn.addEventListener("click", () => withBusy(btn, "Saving…", async () => {
        try {
          await saveDiscoverDeck("meta", Number(btn.getAttribute("data-meta-save")));
          setStatus("Deck saved to library.", false);
        } catch (err) {
          setStatus(err.message || "Could not save meta deck.", true);
        }
      }));
    });
    Array.from(root.querySelectorAll("[data-meta-wizard]")).forEach((btn) => {
      btn.addEventListener("click", () => withBusy(btn, "Opening...", async () => {
        try {
          await bringDiscoverDeckToWizard("meta", Number(btn.getAttribute("data-meta-wizard")));
        } catch (err) {
          setStatus(err.message || "Could not bring deck to wizard.", true);
        }
      }));
    });
    renderMetaStatus();
  }

  function renderCommunity() {
    const root = document.getElementById("community-list");
    if (!root) return;
    if (!state.communityDecks.length) {
      root.innerHTML = '<div class="deck-card-empty">No public beta decks match this query yet.</div>';
      return;
    }
    root.innerHTML = (state.communityDecks || [])
      .map((row, idx) => {
        const legend = String((row.deck && row.deck.legendTitle) || "").trim();
        const leaderInfo = lookupCard(legend);
        const owner = String(row.ownerDisplayName || "").trim() || "Beta User";
        const published = row.publishedAt ? new Date(row.publishedAt).toLocaleDateString() : "Unpublished";
        const likeCount = Number(row.likeCount || 0);
        const likedByMe = Boolean(row.likedByMe);
        const likeLabel = likedByMe ? `♥ ${likeCount}` : `♡ ${likeCount}`;
        const likeClass = likedByMe ? "card-action-btn is-liked" : "card-action-btn secondary";
        const actions =
          `<button type="button" class="card-action-btn secondary" data-community-view="${idx}">View</button>` +
          `<button type="button" class="card-action-btn" data-community-wizard="${idx}">Bring to Wizard</button>` +
          `<button type="button" class="${likeClass}" data-community-like="${idx}" data-deck-id="${escAttr(row.id)}" data-liked="${likedByMe ? "1" : "0"}">${likeLabel}</button>` +
          (!row.isOwner ? `<button type="button" class="card-action-btn" data-community-save="${idx}">Save to Library</button>` : "");
        return tileHtml({
          title: row.name || "Public Deck",
          imageUrl: leaderInfo && leaderInfo.imageUrl ? leaderInfo.imageUrl : "",
          subtitle: `${owner} | ${legend || "No legend"}`,
          meta: `${published}`,
          stats: `${row.isOwner ? "Your deck" : "Community"}`,
          badge: row.isOwner ? "Mine" : "Public",
          badgeClass: "is-bottom-right",
          actions
        });
      })
      .join("");

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-community-view]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        openMetaDetailModal(Number(btn.getAttribute("data-community-view")), "community");
      });
    });
    Array.from(root.querySelectorAll("[data-community-like]")).forEach((btn) => {
      btn.addEventListener("click", () => withBusy(btn, "…", async () => {
        const idx = Number(btn.getAttribute("data-community-like"));
        const deckId = btn.getAttribute("data-deck-id") || "";
        const wasLiked = btn.getAttribute("data-liked") === "1";
        try {
          if (wasLiked) {
            await api(`/api/decks/public/${encodeURIComponent(deckId)}/like`, { method: "DELETE" });
          } else {
            await api(`/api/decks/public/${encodeURIComponent(deckId)}/like`, { method: "POST" });
          }
          // Optimistic update in state
          if (state.communityDecks[idx]) {
            const row = state.communityDecks[idx];
            state.communityDecks[idx] = {
              ...row,
              likedByMe: !wasLiked,
              likeCount: Math.max(0, Number(row.likeCount || 0) + (wasLiked ? -1 : 1))
            };
          }
          renderCommunity();
        } catch (err) {
          setStatus(err.message || "Could not update like.", true);
        }
      }));
    });
    Array.from(root.querySelectorAll("[data-community-save]")).forEach((btn) => {
      btn.addEventListener("click", () => withBusy(btn, "Saving…", async () => {
        try {
          await saveDiscoverDeck("community", Number(btn.getAttribute("data-community-save")));
          setStatus("Deck saved to library.", false);
        } catch (err) {
          setStatus(err.message || "Could not save community deck.", true);
        }
      }));
    });
    Array.from(root.querySelectorAll("[data-community-wizard]")).forEach((btn) => {
      btn.addEventListener("click", () => withBusy(btn, "Opening...", async () => {
        try {
          await bringDiscoverDeckToWizard("community", Number(btn.getAttribute("data-community-wizard")));
        } catch (err) {
          setStatus(err.message || "Could not bring community deck to wizard.", true);
        }
      }));
    });
  }

  function metaSortByValue() {
    const select = document.getElementById("meta-sort-by");
    const raw = String((select && select.value) || "recommendation").trim().toLowerCase();
    if (!raw) return "recommendation";
    if (["recent", "recommendation", "meta", "competitive", "price", "buildability"].includes(raw)) return raw;
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

  function eligibleSideboardCards(query) {
    const needle = normalizeCardKey(query || "");
    const allowed = new Set((state.eligibility.allowedSideboardCardTypes || ["Unit", "Gear", "Spell"]).map((v) => String(v)));
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

  function applySideboardCardDelta(title, delta) {
    const raw = String(title || "").trim();
    const key = canonicalTitle(raw);
    if (!key || !delta) return false;
    const card = lookupCard(key);
    if (card && String(card.cardType || "").trim() === "Legend") return false;
    if (raw && raw !== key) {
      const aliasQty = Math.max(0, Number(state.deck.sideboard[raw] || 0) || 0);
      if (aliasQty > 0) {
        state.deck.sideboard[key] = (Math.max(0, Number(state.deck.sideboard[key] || 0) || 0) || 0) + aliasQty;
        delete state.deck.sideboard[raw];
      }
    }
    const current = Math.max(0, Number(state.deck.sideboard[key] || 0) || 0);
    const cap = Math.max(1, mainCopyCapForTitle(key));
    const sideboardCap = Math.max(0, Number(state.eligibility.sideboardMax || 0) || 0);
    if (delta > 0 && current >= cap) return false;
    if (delta > 0 && sideboardCap > 0 && sideboardTotal() >= sideboardCap) return false;
    const next = Math.max(0, Math.min(cap, current + delta));
    if (next === current) return false;
    if (next <= 0) {
      delete state.deck.sideboard[key];
    } else {
      state.deck.sideboard[key] = next;
    }
    return true;
  }

  function adjustSideboardCard(title, delta) {
    if (!applySideboardCardDelta(title, delta)) return;
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
    const formatName = String(state.deck.format || "constructed").trim() || "constructed";
    const payload = await api(
      `/api/decks/eligibility?format=${encodeURIComponent(formatName)}&legendTitle=${encodeURIComponent(
        String(legendTitle || "").trim()
      )}&limit=1000`
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

  function fallbackLegendCards() {
    const legends = (state.cards || []).filter((card) => {
      const cardType = String((card && card.cardType) || "").trim();
      const superType = String((card && card.superType) || "").trim();
      return cardType === "Legend" || superType === "Legend";
    });
    legends.sort((a, b) => compareCardsBySetAndNumber(a, a.title, b, b.title));
    const seen = new Set();
    return legends.filter((card) => {
      const canonical = canonicalTitle(card.title);
      if (!canonical) return false;
      if (seen.has(canonical)) return false;
      seen.add(canonical);
      return true;
    });
  }

  function fallbackChampionCards() {
    const champions = (state.cards || []).filter((card) => {
      const cardType = String((card && card.cardType) || "").trim();
      const superType = String((card && card.superType) || "").trim();
      return cardType === "Champion" || superType === "Champion";
    });
    champions.sort((a, b) => compareCardsBySetAndNumber(a, a.title, b, b.title));
    const seen = new Set();
    return champions.filter((card) => {
      const canonical = canonicalTitle(card.title);
      if (!canonical) return false;
      if (seen.has(canonical)) return false;
      seen.add(canonical);
      return true;
    });
  }

  function autoBuilderLegendCards() {
    const rows = Array.isArray(state.autoBuilder.eligibility && state.autoBuilder.eligibility.legends)
      ? state.autoBuilder.eligibility.legends
      : [];
    return rows.length ? rows : fallbackLegendCards();
  }

  function autoBuilderChampionCards() {
    const rows = Array.isArray(state.autoBuilder.eligibility && state.autoBuilder.eligibility.champions)
      ? state.autoBuilder.eligibility.champions
      : [];
    return rows.length ? rows : fallbackChampionCards();
  }

  async function refreshAutoBuilderEligibility(legendTitle, options) {
    const opts = options || {};
    const formatName = String(state.deck.format || "constructed").trim() || "constructed";
    const payload = await api(
      `/api/decks/eligibility?format=${encodeURIComponent(formatName)}&legendTitle=${encodeURIComponent(
        String(legendTitle || "").trim()
      )}&limit=1000`
    );
    const legends = Array.isArray(payload && payload.legends) ? payload.legends : [];
    const champions = Array.isArray(payload && payload.champions) ? payload.champions : [];
    state.autoBuilder.eligibility = {
      legends: legends.length ? legends : fallbackLegendCards(),
      champions: champions.length ? champions : fallbackChampionCards()
    };
    const currentChampion = canonicalTitle(state.autoBuilder.chosenChampionTitle || "");
    if (currentChampion) {
      const available = new Set(state.autoBuilder.eligibility.champions.map((card) => canonicalTitle(card.title)));
      if (available.size && !available.has(currentChampion)) {
        state.autoBuilder.chosenChampionTitle = "";
      }
    }
    if (opts.render !== false) renderAutoBuilder();
    return payload;
  }

  async function selectLegend(title) {
    state.deck.legendTitle = canonicalTitle(title);
    await refreshEligibility(state.deck.legendTitle, { applyRecommended: true, validate: true });
  }

  async function selectAutoBuilderLegend(title) {
    state.autoBuilder.legendTitle = canonicalTitle(title);
    await refreshAutoBuilderEligibility(state.autoBuilder.legendTitle, { render: false });
    renderAutoBuilder();
  }

  function selectAutoBuilderChampion(title) {
    state.autoBuilder.chosenChampionTitle = canonicalTitle(title);
    renderAutoBuilder();
  }

  function mainSearchQuery() {
    const input = document.getElementById("main-card-search");
    return ((input && input.value) || "").trim();
  }

  let _lastMainSearchListKey = "";
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
      _lastMainSearchListKey = "";
      root.innerHTML = '<div class="deck-card-empty">No cards match the current filters.</div>';
      return;
    }

    // Key on the ordered card list. If only deck quantities changed (not which cards are shown),
    // skip the expensive full innerHTML rebuild and just patch button states in-place.
    const listKey = rows.map((c) => c.title).join("\0");
    if (listKey === _lastMainSearchListKey && root.firstChild) {
      root.querySelectorAll("[data-main-add]").forEach((btn) => {
        const title = btn.getAttribute("data-main-add") || "";
        if (!title) return;
        const cap = Math.max(1, mainCopyCapForTitle(title));
        const qty = Math.max(0, Number(state.deck.main[title] || 0) || 0);
        const atCap = qty >= cap;
        btn.disabled = atCap;
        btn.textContent = atCap ? "Full" : "Add";
      });
      return;
    }
    _lastMainSearchListKey = listKey;

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

  function sideboardSearchQuery() {
    const input = document.getElementById("sideboard-search");
    return ((input && input.value) || "").trim();
  }

  function renderSideboardList() {
    const root = document.getElementById("sideboard-list");
    if (!root) return;
    const query = sideboardSearchQuery();
    const rows = eligibleSideboardCards(query);
    const sideboardCap = Math.max(0, Number(state.eligibility.sideboardMax || 0) || 0);
    if (!rows.length) {
      root.innerHTML = '<div class="deck-card-empty">No sideboard-legal cards match this query.</div>';
      return;
    }
    root.innerHTML = rows
      .map((card) => {
        const cap = Math.max(1, mainCopyCapForTitle(card.title));
        const qty = Math.max(0, Number(state.deck.sideboard[card.title] || 0) || 0);
        const sideboardAtCap = sideboardCap > 0 && sideboardTotal() >= sideboardCap;
        const disableInc = qty >= cap || sideboardAtCap;
        const actions =
          `<div class="qty-stepper sideboard-stepper">` +
          `<button type="button" class="step-btn" data-side-dec="${escAttr(card.title)}"${qty <= 0 ? " disabled" : ""}>-</button>` +
          `<span class="step-value">${esc(qty)}/${esc(cap)}</span>` +
          `<button type="button" class="step-btn" data-side-inc="${escAttr(card.title)}"${disableInc ? " disabled" : ""}>+</button>` +
          `</div>`;
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
    Array.from(root.querySelectorAll("[data-side-inc]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        adjustSideboardCard(btn.getAttribute("data-side-inc") || "", 1);
      });
    });
    Array.from(root.querySelectorAll("[data-side-dec]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        adjustSideboardCard(btn.getAttribute("data-side-dec") || "", -1);
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
    const coverage = summarizeMainDeckCollectionCoverage();
    const missingByTitle = coverage.missingByTitle || {};
    if (!entries.length) {
      root.innerHTML = '<div class="deck-card-empty">No library cards yet. Drag from A or press Add.</div>';
      bindMainDeckDropZone();
      return;
    }

    const shelfEntries = entries.flatMap(([title, qty]) => {
      const card = lookupCard(title);
      const subtitle = card ? cardMetaLine(card) : "Unresolved card";
      const totalQty = Math.max(0, Number(qty) || 0);
      const missingRow = missingByTitle[title] || null;
      const missingQty = missingRow ? Math.max(0, Number(missingRow.missing || 0) || 0) : 0;
      const ownedQty = Math.max(0, totalQty - missingQty);
      const hasMissing = missingQty > 0;
      const isPartialMissing = hasMissing && ownedQty > 0;
      const base = {
        title,
        card,
        subtitle,
        totalQty,
        missingQty,
        ownedQty,
        hasMissing,
        isPartialMissing
      };
      if (isPartialMissing) {
        return [{ ...base, slotKind: "owned" }, { ...base, slotKind: "missing-ghost" }];
      }
      return [{ ...base, slotKind: "owned" }];
    });

    const cols = computeMainDeckCols(root, shelfEntries.length);
    const rows = chunkMainDeckEntries(shelfEntries, cols);

    root.innerHTML =
      `<div class="main-shelf-stack" style="--main-row-cols:${escAttr(cols)};">` +
      rows
        .map((rowEntries) => {
          const cards = rowEntries
            .map((entry) => {
              const {
                title,
                card,
                subtitle,
                totalQty,
                missingQty,
                hasMissing,
                isPartialMissing,
                slotKind
              } = entry;
              const isGhostSlot = slotKind === "missing-ghost";
              const replacementInteractive = state.analysis.active && hasMissing;
              const chips = [];
              if (isGhostSlot && hasMissing) {
                chips.push(
                  `<span class="main-missing-chip is-missing is-ghost-count" title="Need ${escAttr(
                    missingQty
                  )} additional copies">Missing x${esc(missingQty)}</span>`
                );
              } else if (replacementInteractive && !isPartialMissing) {
                chips.push(
                  `<button type="button" class="main-missing-chip is-missing" data-missing-open="${escAttr(title)}" title="Need ${escAttr(
                    missingQty
                  )} additional copies">Missing x${esc(missingQty)}</button>`
                );
              }
              const extraClass = isGhostSlot
                ? "compact is-collection-missing is-collection-ghost"
                : `compact${hasMissing && !isPartialMissing ? " is-collection-missing" : ""}${isPartialMissing ? " is-collection-partial" : ""}`;
              return tileHtml({
                title,
                imageUrl: card && card.imageUrl ? card.imageUrl : "",
                subtitle,
                meta: subtitle,
                stats: card ? cardStatsLine(card) : "",
                artOverlay: chips.length ? `<div class="main-missing-chip-stack">${chips.join("")}</div>` : "",
                disableFoil: isGhostSlot,
                extraAttrs:
                  (replacementInteractive ? `data-main-missing-card="${escAttr(title)}"` : "") +
                  (isGhostSlot ? ' data-main-ghost-card="1"' : ""),
                extraClass,
                shelfOnly: true
              });
            })
            .join("");

          const steppers = rowEntries
            .map((entry) => {
              const { title, totalQty, ownedQty, missingQty, hasMissing, slotKind } = entry;
              if (slotKind === "missing-ghost") {
                return (
                  `<div class="main-shelf-stepper-slot is-ghost-slot">` +
                  `<button type="button" class="card-action-btn danger main-ghost-remove-btn" data-main-remove-missing="${escAttr(
                    title
                  )}" data-main-remove-count="${escAttr(missingQty)}">Remove x${esc(missingQty)}</button>` +
                  `</div>`
                );
              }
              const cap = Math.max(1, mainCopyCapForTitle(title));
              const disableInc = Number(totalQty) >= cap;
              const shownQty = hasMissing ? ownedQty : totalQty;
              return (
                `<div class="main-shelf-stepper-slot">` +
                `<div class="qty-stepper main-shelf-stepper">` +
                `<button type="button" class="step-btn" data-main-dec="${escAttr(title)}">-</button>` +
                `<span class="step-value">${esc(shownQty)}/${esc(cap)}</span>` +
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
    Array.from(root.querySelectorAll("[data-main-remove-missing]")).forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const title = btn.getAttribute("data-main-remove-missing") || "";
        const missingQty = Math.max(0, Number(btn.getAttribute("data-main-remove-count") || 0) || 0);
        if (!title || missingQty <= 0) return;
        if (!applyMainCardDelta(title, -missingQty)) return;
        renderDeckWorkbench();
        scheduleValidation();
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

      // Cache the bounding rect to avoid forced layout on every pointermove.
      let _physRect = null;
      const driveFromPointer = (ev) => {
        if (!_physRect || !_physRect.width || !_physRect.height) return;
        // Map pointer location in card bounds to rotation/lift vectors.
        const px = ((ev.clientX - _physRect.left) / _physRect.width) * 2 - 1;
        const py = ((ev.clientY - _physRect.top) / _physRect.height) * 2 - 1;
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
        _physRect = null;
        motion.tx = 0;
        motion.ty = 0;
        motion.lift = 0;
        motion.fx = 0;
        motion.fy = 0;
        motion.shadow = 0;
        requestAnimation();
      };

      tile.addEventListener("pointerenter", (ev) => {
        _physRect = art.getBoundingClientRect(); // read once on enter
        driveFromPointer(ev);
      }, { passive: true });
      tile.addEventListener("pointermove", driveFromPointer, { passive: true });
      tile.addEventListener("pointerleave", reset, { passive: true });
      tile.addEventListener("pointercancel", reset, { passive: true });
      tile.addEventListener("pointerup", reset, { passive: true });
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
    renderFormatSelector();
    syncDeckMetaControls();
    updateDeckSaveState();
    const deckName = document.getElementById("deck-name");
    if (deckName && deckName.value !== state.deck.name) {
      deckName.value = state.deck.name;
    }
    const formatSelect = document.getElementById("deck-format-select");
    if (formatSelect && formatSelect.value !== state.deck.format) {
      formatSelect.value = state.deck.format || "constructed";
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

    const sideboardBadge = document.getElementById("sideboard-total-badge");
    if (sideboardBadge) {
      sideboardBadge.textContent = `${sideboardTotal()} / ${state.eligibility.sideboardMax || 8}`;
    }
    const sideboardRuleNote = document.getElementById("sideboard-rule-note");
    if (sideboardRuleNote) {
      sideboardRuleNote.textContent = `Sideboard cap ${state.eligibility.sideboardMax || 8}. Combined copy limits with Main Deck are checked in validation.`;
    }

    renderRuneSteppers();
    renderBattlefieldSlots();
    renderMainSearchResults();
    renderSideboardList();
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
    else if (kind === "auto-builder-legend") rows = autoBuilderLegendCards();
    else if (kind === "auto-builder-champion") rows = autoBuilderChampionCards();
    else if (kind === "battlefield") rows = state.eligibility.battlefields || [];
    else if (kind === "main") rows = eligibleMainCards(query);
    else if (kind === "sideboard") rows = eligibleSideboardCards(query);

    if (!needle || kind === "main" || kind === "sideboard") return rows;
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
        } else if (state.picker.kind === "auto-builder-legend") {
          await selectAutoBuilderLegend(title);
        } else if (state.picker.kind === "auto-builder-champion") {
          selectAutoBuilderChampion(title);
        } else if (state.picker.kind === "battlefield") {
          selectBattlefield(state.picker.battlefieldIndex, title);
        } else if (state.picker.kind === "main") {
          adjustMainCard(title, 1);
        } else if (state.picker.kind === "sideboard") {
          adjustSideboardCard(title, 1);
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
    else if (kind === "auto-builder-legend") title.textContent = "Filter By Legend";
    else if (kind === "auto-builder-champion") title.textContent = "Filter By Champion";
    else if (kind === "battlefield") title.textContent = "Choose Battlefield";
    else if (kind === "sideboard") title.textContent = "Add Sideboard Card";
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

  function renderFormatSelector() {
    const select = document.getElementById("deck-format-select");
    if (!select) return;
    const rows = Array.isArray(state.formats) ? state.formats : [];
    if (!rows.length) {
      select.innerHTML = '<option value="constructed">constructed</option>';
      select.value = "constructed";
      state.deck.format = "constructed";
      return;
    }
    select.innerHTML = rows
      .map((row) => {
        const name = String((row && row.format) || "").trim();
        if (!name) return "";
        const label = String((row && row.description) || "").trim();
        return `<option value="${escAttr(name)}">${esc(label ? `${name} - ${label}` : name)}</option>`;
      })
      .join("");
    const allowed = new Set(rows.map((row) => String((row && row.format) || "").trim()).filter(Boolean));
    if (!allowed.has(state.deck.format)) {
      const fallback = rows.find((row) => Boolean(row && row.isDefault)) || rows[0];
      state.deck.format = String((fallback && fallback.format) || "constructed").trim() || "constructed";
    }
    select.value = state.deck.format;
  }

  async function loadFormats() {
    state.formats = await api("/api/decks/formats");
    renderFormatSelector();
  }

  function toggleDeckLibraryDrawer(open) {
    const sidebar = document.getElementById("deck-library-sidebar");
    if (!sidebar) return;
    const isOpen = open !== undefined ? Boolean(open) : !sidebar.classList.contains("is-drawer-open");
    sidebar.classList.toggle("is-drawer-open", isOpen);
    document.body.classList.toggle("deck-drawer-open", isOpen);
  }

  async function loadLibrary() {
    const builtRoot = document.getElementById("library-built-gallery");
    const savedRoot = document.getElementById("library-saved-gallery");
    const illegalRoot = document.getElementById("library-illegal-gallery");
    if (builtRoot) builtRoot.innerHTML = skeletonTiles(2);
    if (savedRoot) savedRoot.innerHTML = skeletonTiles(2);
    if (illegalRoot) illegalRoot.innerHTML = skeletonTiles(2);
    const query = String(((document.getElementById("library-search") || {}).value || "")).trim();
    const path = query ? `/api/decks/library?query=${encodeURIComponent(query)}` : "/api/decks/library";
    state.library = await api(path);
    renderLibrary();
  }

  async function loadMetaDecks(options) {
    const opts = options || {};
    const root = document.getElementById("meta-list");
    if (root && !opts.preserveExisting) root.innerHTML = skeletonTiles(6);
    const query = ((document.getElementById("meta-search") || {}).value || "").trim();
    const sortBy = metaSortByValue();
    const sortDir = metaSortDirValue(sortBy);
    const includeCollEl = document.getElementById("meta-include-collection");
    const includeCollection = includeCollEl ? includeCollEl.checked : true;
    state.metaIncludeCollection = includeCollection;
    state.metaDecks = await api(
      `/api/meta/decks?limit=120&query=${encodeURIComponent(query)}&sortBy=${encodeURIComponent(sortBy)}&sortDir=${encodeURIComponent(
        sortDir
      )}&includeCollection=${includeCollection}`
    );
    try {
      if (opts.refreshStatus !== false) {
        await loadMetaStatus();
      }
    } catch (_err) {
      // Keep search results usable even if freshness lookup fails.
    }
    renderMeta();
  }

  function communitySortByValue() {
    const select = document.getElementById("community-sort-by");
    const raw = String((select && select.value) || "updated").trim().toLowerCase();
    if (["updated", "likes", "name"].includes(raw)) return raw;
    return "updated";
  }

  async function loadCommunityDecks() {
    const root = document.getElementById("community-list");
    if (root) root.innerHTML = skeletonTiles(6);
    const query = String(((document.getElementById("meta-search") || {}).value || "")).trim();
    const sortBy = communitySortByValue();
    state.communityDecks = await api(`/api/decks/public?limit=120&query=${encodeURIComponent(query)}&sortBy=${encodeURIComponent(sortBy)}`);
    renderCommunity();
  }

  async function loadDiscoverResults() {
    if (state.ui.discoverTab === "community") {
      await loadCommunityDecks();
      return;
    }
    await loadMetaDecks();
  }

  async function loadMetaStatus() {
    state.metaStatus = await api("/api/meta/status");
    renderMetaStatus();
  }

  async function refreshMetaIndex() {
    state.metaStatus = await api("/api/meta/refresh", { method: "POST" });
    renderMetaStatus();
  }

  async function refreshMetaSearchResults() {
    try {
      if (state.ui.loadedWorkspaces && state.ui.loadedWorkspaces.discover) {
        await Promise.all([loadMetaDecks(), loadCommunityDecks()]);
      } else {
        await loadMetaDecks();
      }
    } catch (_err) {
      // Keep write actions successful even if deck-search refresh fails.
    }
  }

  function autoBuilderRequestBody() {
    return {
      top: 24,
      rankingMode: state.autoBuilder.rankingMode,
      strategyMode: state.autoBuilder.strategyMode,
      legendTitle: state.autoBuilder.legendTitle,
      chosenChampionTitle: state.autoBuilder.chosenChampionTitle,
      onlyBuildable: state.autoBuilder.onlyBuildable
    };
  }

  function autoBuilderSelectedRecommendation() {
    const idx = Number(state.autoBuilder.selectedIndex || 0);
    const rows = Array.isArray(state.autoBuilder.recommendations) ? state.autoBuilder.recommendations : [];
    if (idx < 0 || idx >= rows.length) return null;
    return rows[idx] || null;
  }

  function renderAutoBuilderStatus() {
    const root = document.getElementById("auto-builder-status-line");
    if (!root) return;
    const status = state.autoBuilder.status;
    if (state.autoBuilder.loading) {
      root.textContent = "Generating recommendations from the current model and collection...";
      return;
    }
    if (!status) {
      root.textContent = "Auto Builder status unavailable.";
      return;
    }
    const generatedAt = status.generatedAt ? new Date(status.generatedAt).toLocaleString() : "never";
    const err = status.lastError ? ` | Last error: ${status.lastError}` : "";
    const warning = Array.isArray(status.runtimeWarnings) && status.runtimeWarnings.length
      ? ` | Compatibility: ${status.runtimeWarnings[0]}`
      : "";
    const strictHit = Number(status.strictBuildableRecommendationHitRate || 0) * 100;
    const strictEmpty = Number(status.strictBuildableEmptyResultRate || 0) * 100;
    const winCount = status.selectedWinConditionCount || status.winConditionCount || 0;
    const synergyCount = status.selectedSynergyClusterCount || status.synergyClusterCount || 0;
    root.textContent = `Model ${status.enabled ? "enabled" : "disabled"} | ${status.trainingDeckCount || 0} training decks | ${winCount} selected win conditions | ${synergyCount} selected synergy clusters | strict buildable ${strictHit.toFixed(1)}% hit / ${strictEmpty.toFixed(1)}% empty | generated ${generatedAt}${err}${warning}`;
  }

  function renderAutoBuilderFilters() {
    setSlotCard({
      buttonId: "auto-builder-legend-btn",
      imageId: "auto-builder-legend-img",
      nameId: "auto-builder-legend-name",
      title: state.autoBuilder.legendTitle,
      placeholder: "Any Legend"
    });
    setSlotCard({
      buttonId: "auto-builder-champion-btn",
      imageId: "auto-builder-champion-img",
      nameId: "auto-builder-champion-name",
      title: state.autoBuilder.chosenChampionTitle,
      placeholder: "Any Champion"
    });
  }

  function renderAutoBuilderSummary() {
    const root = document.getElementById("auto-builder-summary");
    if (!root) return;
    const rows = Array.isArray(state.autoBuilder.recommendations) ? state.autoBuilder.recommendations : [];
    const selected = autoBuilderSelectedRecommendation();
    const status = state.autoBuilder.status || {};
    const effectiveRankingMode = state.autoBuilder.onlyBuildable
      ? "competitive"
      : (String(state.autoBuilder.rankingMode || "collection").trim().toLowerCase() || "collection");
    const modeLabel =
      effectiveRankingMode === "competitive"
        ? "Competitive Score"
        : effectiveRankingMode === "hybrid"
          ? "Hybrid"
          : "Collection First";
    const strategyLabel =
      state.autoBuilder.strategyMode === "pure_generate"
        ? "Pure Generate"
        : state.autoBuilder.strategyMode === "seed_adapt"
          ? "Seed Adapt"
          : "Hybrid";
    const tiles = [];
    if (state.autoBuilder.loading) {
      tiles.push({ label: "Mode", value: modeLabel });
      tiles.push({ label: "Strategy", value: strategyLabel });
      tiles.push({ label: "Status", value: "Generating" });
      tiles.push({ label: "Focus", value: state.autoBuilder.onlyBuildable ? "Only buildable" : "All candidates" });
    } else if (selected) {
      const completion = Number(selected.completionPct || 0).toFixed(1);
      tiles.push({ label: "Selected", value: selected.winConditionLabel || "Auto Deck" });
      tiles.push({ label: "Buildability", value: selected.isBuildable ? "Ready now" : `${completion}% complete` });
      tiles.push({ label: "Score", value: `${Number(selected.rankingScore || 0).toFixed(1)} ranking / ${Number(selected.competitiveScore || 0).toFixed(1)} comp` });
      tiles.push({ label: "Cost To Finish", value: selected.estimatedCompletionCost == null ? "N/A" : formatMoney(selected.estimatedCompletionCost) });
    } else {
      tiles.push({ label: "Model", value: status.enabled ? "Ready" : "Disabled" });
      tiles.push({ label: "Training Decks", value: String(status.trainingDeckCount || 0) });
      tiles.push({ label: "Selected Counts", value: `${status.selectedWinConditionCount || status.winConditionCount || 0} WC / ${status.selectedSynergyClusterCount || status.synergyClusterCount || 0} SC` });
      tiles.push({ label: "Strict Buildable", value: `${(Number(status.strictBuildableRecommendationHitRate || 0) * 100).toFixed(1)}% hit` });
      tiles.push({ label: "Strategy", value: `${modeLabel} / ${strategyLabel}` });
    }
    const sourceCounts = status.sourceCounts && typeof status.sourceCounts === "object" ? status.sourceCounts : {};
    const sourceSummary = Object.keys(sourceCounts)
      .sort((a, b) => String(a).localeCompare(String(b)))
      .map((key) => `${key}: ${sourceCounts[key]}`)
      .slice(0, 4)
      .join(" | ");
    const helper = rows.length
      ? `${rows.length} recommendation${rows.length === 1 ? "" : "s"} loaded.`
      : sourceSummary || "Generate to produce collection-aware deck candidates.";
    root.innerHTML =
      `<div class="auto-builder-summary-grid">` +
      tiles
        .map((tile) => `<article class="auto-builder-summary-card"><small>${esc(tile.label)}</small><strong>${esc(tile.value)}</strong></article>`)
        .join("") +
      `</div>` +
      `<p class="auto-builder-summary-note">${esc(helper)}</p>`;
  }

  function renderAutoBuilderDetail() {
    const root = document.getElementById("auto-builder-detail");
    if (!root) return;
    if (state.autoBuilder.loading) {
      root.innerHTML = '<div class="deck-card-empty">Generating deck candidates. This can take a few seconds on larger models.</div>';
      return;
    }
    const row = autoBuilderSelectedRecommendation();
    if (!row) {
      root.innerHTML = '<div class="deck-card-empty">Generate recommendations to inspect a synthesized deck.</div>';
      return;
    }
    const missing = Array.isArray(row.missingCards) ? row.missingCards : [];
    const replacementSuggestions = Array.isArray(row.replacementSuggestions) ? row.replacementSuggestions : [];
    const explanations = Array.isArray(row.explanations) ? row.explanations : [];
    const seedDecks = Array.isArray(row.seedDecks) ? row.seedDecks : [];
    const deck = row.deck || {};
    const mainRows = Object.entries(deck.main || {})
      .sort((a, b) => compareTitlesByCatalogOrder(a[0], b[0]))
      .map(([title, qty]) => `<div>${esc(title)} x${esc(qty)}</div>`)
      .join("") || '<div class="ok">No main-deck cards.</div>';
    const missingRows = missing
      .slice(0, 24)
      .map((item) => {
        const url = String(item.tcgplayer_url || "").trim();
        return (
          `<div class="auto-builder-detail-row">` +
          `<span>${esc(item.card)} x${esc(item.missing)}</span>` +
          `<small>${item.estimated_missing_cost == null ? "Cost n/a" : formatMoney(item.estimated_missing_cost)}${url ? ` | <a href="${escAttr(url)}" target="_blank" rel="noopener noreferrer">TCGplayer</a>` : ""}</small>` +
          `</div>`
        );
      })
      .join("") || '<div class="ok">No missing cards.</div>';
    const replacementRows = replacementSuggestions
      .slice(0, 12)
      .map((item) => {
        const options = Array.isArray(item.options) ? item.options.slice(0, 3) : [];
        const line = options.map((opt) => `${esc(opt.card)} (${esc(opt.source || "hybrid")} | ${esc(opt.score)})`).join(" | ");
        return `<div class="auto-builder-detail-row"><span>${esc(item.card)}</span><small>${line || "No learned replacement."}</small></div>`;
      })
      .join("") || '<div class="ok">No replacement plan needed.</div>';
    const explanationRows = explanations
      .map((item) => `<div class="auto-builder-detail-row"><span>${esc(item.label || item.kind || "Reason")}</span><small>${esc(item.value || "")}</small></div>`)
      .join("") || '<div class="ok">No explanation rows.</div>';
    const seedRows = seedDecks
      .map((item) => `<div class="auto-builder-detail-row"><span>${esc(item.deckName || item.deck_name || "Seed Deck")}</span><small>${esc(item.source || "meta")} | score ${esc(item.score)}</small></div>`)
      .join("") || '<div class="ok">No seed shells used.</div>';
    const synergyLabels = Array.isArray(row.synergyClusterLabels) ? row.synergyClusterLabels : [];
    root.innerHTML =
      `<div class="auto-builder-detail-hero">` +
      `<div class="auto-builder-detail-title">${esc(row.winConditionLabel || "Unknown win condition")}</div>` +
      `<div class="auto-builder-detail-metrics">` +
      `<span>Build ${esc(row.buildMode || "hybrid")}</span>` +
      `<span>Competitive ${esc(Number(row.competitiveScore || 0).toFixed(1))}</span>` +
      `<span>Ranking ${esc(Number(row.rankingScore || 0).toFixed(1))}</span>` +
      `<span>Completion ${esc(Number(row.completionPct || 0).toFixed(1))}%</span>` +
      `<span>Cost ${row.estimatedCompletionCost == null ? "N/A" : esc(formatMoney(row.estimatedCompletionCost))}</span>` +
      `</div>` +
      `<div class="auto-builder-detail-subtitle">${esc((deck.legendTitle || "-") + " / " + (deck.chosenChampionTitle || "-"))}</div>` +
      `<div class="auto-builder-detail-tags">${synergyLabels.length ? esc(synergyLabels.join(" | ")) : "No synergy package labels available."}</div>` +
      `</div>` +
      `<div class="auto-builder-detail-section"><h4>Deck</h4>${mainRows}</div>` +
      `<div class="auto-builder-detail-section"><h4>Missing Cards</h4>${missingRows}</div>` +
      `<div class="auto-builder-detail-section"><h4>Replacement Plan</h4>${replacementRows}</div>` +
      `<div class="auto-builder-detail-section"><h4>Why This Deck</h4>${explanationRows}</div>` +
      `<div class="auto-builder-detail-section"><h4>Seed Decks</h4>${seedRows}</div>`;
  }

  function renderAutoBuilderResults() {
    const root = document.getElementById("auto-builder-results");
    if (!root) return;
    if (state.autoBuilder.loading) {
      root.innerHTML =
        '<div class="auto-builder-loading-list">' +
        Array.from({ length: 3 })
          .map(() => '<div class="auto-builder-loading-card"></div>')
          .join("") +
        "</div>";
      renderAutoBuilderDetail();
      return;
    }
    const rows = Array.isArray(state.autoBuilder.recommendations) ? state.autoBuilder.recommendations : [];
    if (!rows.length) {
      root.innerHTML = '<div class="deck-card-empty">No recommendations yet. Run Generate or use the Manual Mode auto-complete actions.</div>';
      renderAutoBuilderDetail();
      return;
    }
    root.innerHTML = rows
      .map((row, idx) => {
        const deck = row.deck || {};
        const title = row.deck && row.deck.name ? row.deck.name : `${row.winConditionLabel || "Auto Deck"} ${idx + 1}`;
        const leaderInfo = lookupCard((deck && deck.legendTitle) || "");
        const leaderTitle = String((deck && deck.legendTitle) || "").trim();
        const championTitle = String((deck && deck.chosenChampionTitle) || "").trim();
        const imageUrl = leaderInfo && leaderInfo.imageUrl ? leaderInfo.imageUrl : cardBackFor(title);
        const completionText = `${Number(row.completionPct || 0).toFixed(1)}%`;
        const priceText = row.estimatedCompletionCost == null ? "N/A" : formatMoney(row.estimatedCompletionCost);
        const actions =
          `<button type="button" class="card-action-btn secondary" data-auto-builder-select="${idx}">Inspect</button>` +
          `<button type="button" class="card-action-btn" data-auto-builder-open="${idx}">Open</button>`;
        return (
          `<article class="auto-builder-card ${idx === Number(state.autoBuilder.selectedIndex || 0) ? "is-selected" : ""}"` +
          ` data-preview-title="${escAttr(title)}"` +
          ` data-preview-image="${escAttr(imageUrl)}"` +
          ` data-preview-meta="${escAttr(`${leaderTitle || "-"} | ${championTitle || "-"}`)}"` +
          ` data-preview-stats="${escAttr(`Competitive ${Number(row.competitiveScore || 0).toFixed(1)} | Completion ${completionText}`)}"` +
          ` data-preview-fallback="${escAttr(initials(title))}"` +
          ` data-preview-back="${escAttr(cardBackFor(title))}"` +
          `>` +
          `<div class="auto-builder-card-art-wrap">` +
          `<img class="auto-builder-card-art ${leaderInfo && leaderInfo.imageUrl ? "" : "is-fallback"}" src="${escAttr(imageUrl)}" alt="${escAttr(title)} artwork" data-fallback-src="${escAttr(cardBackFor(title))}" />` +
          `</div>` +
          `<div class="auto-builder-card-body">` +
          `<div class="auto-builder-card-top">` +
          `<div>` +
          `<div class="auto-builder-card-rank">#${idx + 1}</div>` +
          `<div class="auto-builder-card-title">${esc(title)}</div>` +
          `<div class="auto-builder-card-subtitle">${esc(row.winConditionLabel || "Unknown win condition")}</div>` +
          `</div>` +
          `<div class="auto-builder-card-score">${esc(Number(row.rankingScore || 0).toFixed(1))}</div>` +
          `</div>` +
          `<div class="auto-builder-chip-row">` +
          `<span class="auto-builder-chip">${esc(row.buildMode || "hybrid")}</span>` +
          `<span class="auto-builder-chip">${row.isBuildable ? "Buildable" : `Missing ${esc(row.missingCopies || 0)}`}</span>` +
          `<span class="auto-builder-chip">Competitive ${esc(Number(row.competitiveScore || 0).toFixed(1))}</span>` +
          `</div>` +
          `<div class="auto-builder-card-meta">` +
          `<span>${esc(leaderTitle || "-")}</span>` +
          `<span>${esc(championTitle || "-")}</span>` +
          `<span>Completion ${esc(completionText)}</span>` +
          `<span>Cost ${esc(priceText)}</span>` +
          `</div>` +
          `<div class="card-actions auto-builder-card-actions">${actions}</div>` +
          `</div>` +
          `</article>`
        );
      })
      .join("");
    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    bindFoilInteractions(root);
    Array.from(root.querySelectorAll("[data-auto-builder-select]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.autoBuilder.selectedIndex = Number(btn.getAttribute("data-auto-builder-select") || 0);
        renderAutoBuilderResults();
      });
    });
    Array.from(root.querySelectorAll("[data-auto-builder-open]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.autoBuilder.selectedIndex = Number(btn.getAttribute("data-auto-builder-open") || 0);
        try {
          await openAutoBuilderSelectionInManual();
        } catch (err) {
          setStatus(err.message || "Could not open auto-builder deck.", true);
        }
      });
    });
    renderAutoBuilderDetail();
  }

  function renderAutoBuilder() {
    renderAutoBuilderFilters();
    renderAutoBuilderStatus();
    renderAutoBuilderSummary();
    renderAutoBuilderResults();
  }

  async function loadAutoBuilderStatus() {
    state.autoBuilder.status = await api("/api/auto-builder/status");
    renderAutoBuilder();
  }

  async function loadAutoBuilderRecommendations() {
    state.autoBuilder.completionResult = null;
    state.autoBuilder.loading = true;
    renderAutoBuilder();
    try {
      const response = await api("/api/auto-builder/recommendations", {
        method: "POST",
        body: autoBuilderRequestBody()
      });
      state.autoBuilder.recommendations = Array.isArray(response.recommendations) ? response.recommendations : [];
      state.autoBuilder.selectedIndex = 0;
    } finally {
      state.autoBuilder.loading = false;
      renderAutoBuilder();
    }
  }

  async function openAutoBuilderSelectionInManual() {
    const row = autoBuilderSelectedRecommendation();
    if (!row || !row.deck) throw new Error("No auto-builder recommendation selected.");
    await writeDeckToForm(row.deck);
    setStatus(`Opened auto-builder deck: ${row.deck.name || row.winConditionLabel || "Auto Deck"}`, false);
  }

  async function saveAutoBuilderSelection() {
    const row = autoBuilderSelectedRecommendation();
    if (!row || !row.deck) throw new Error("No auto-builder recommendation selected.");
    await api("/api/decks/library", {
      method: "POST",
      body: {
        name: row.deck.name || row.winConditionLabel || "Auto Builder Deck",
        source: row.deck.source || "auto-builder",
        bucket: "saved",
        visibility: "private",
        deck: row.deck
      }
    });
    await loadLibrary();
    setStatus(`Saved auto-builder deck: ${row.deck.name || row.winConditionLabel || "Auto Deck"}`, false);
  }

  async function runAutoBuilderCompletion() {
    const response = await api("/api/auto-builder/complete", {
      method: "POST",
      body: {
        deck: currentDeckFromForm(),
        rankingMode: state.autoBuilder.rankingMode,
        strategyMode: state.autoBuilder.strategyMode
      }
    });
    state.autoBuilder.completionResult = response;
    state.autoBuilder.recommendations = Array.isArray(response.completedCandidates) ? response.completedCandidates : [];
    state.autoBuilder.selectedIndex = 0;
    renderAutoBuilder();
    return response;
  }

  function modelObservationSelectedModel() {
    const rows = Array.isArray(state.modelObservation.models) ? state.modelObservation.models : [];
    const targetId = String(state.modelObservation.selectedModelId || "").trim();
    if (targetId) {
      const match = rows.find((row) => String(row.id || "") === targetId);
      if (match) return match;
    }
    const production = rows.find((row) => row.isProduction);
    return production || rows[0] || null;
  }

  function writeModelObservationForm() {
    const form = state.modelObservation.form || {};
    const labelInput = document.getElementById("model-training-label");
    if (labelInput && document.activeElement !== labelInput) labelInput.value = String(form.label || "");
    const epochsInput = document.getElementById("model-training-epochs");
    if (epochsInput && document.activeElement !== epochsInput) epochsInput.value = String(form.epochs || 12);
  }

  function hydrateModelObservationForm(defaults) {
    if (state.modelObservation.hydrated) return;
    const payload = defaults || {};
    state.modelObservation.form = {
      label: "",
      epochs: Number(payload.epochs || 12) || 12,
    };
    state.modelObservation.hydrated = true;
  }

  function readModelObservationForm() {
    const labelInput = document.getElementById("model-training-label");
    const epochsInput = document.getElementById("model-training-epochs");
    state.modelObservation.form = {
      label: String((labelInput && labelInput.value) || "").trim(),
      epochs: Math.max(1, Number((epochsInput && epochsInput.value) || 12) || 12),
    };
    return state.modelObservation.form;
  }

  function renderModelObservationStatus() {
    const root = document.getElementById("model-observation-status");
    if (!root) return;
    const overview = state.modelObservation.overview || {};
    const status = overview.status || {};
    const summary = (overview.observation && overview.observation.summary) || {};
    if (!status || !Object.keys(status).length) {
      root.innerHTML = '<div class="deck-card-empty">Model observation is unavailable.</div>';
      return;
    }
    const generatedAt = status.generatedAt ? new Date(status.generatedAt).toLocaleString() : "never";
    const warnings = Array.isArray(status.runtimeWarnings) ? status.runtimeWarnings.filter(Boolean) : [];
    const sourceCounts = status.sourceCounts && typeof status.sourceCounts === "object" ? status.sourceCounts : {};
    const sourceList = Object.keys(sourceCounts)
      .sort((a, b) => String(a).localeCompare(String(b)))
      .map((key) => `<div class="model-mini-row"><span>${esc(key)}</span><strong>${esc(sourceCounts[key])}</strong></div>`)
      .join("") || '<div class="model-mini-row"><span>Sources</span><strong>0</strong></div>';
    const warningNote = warnings.length
      ? `<p class="model-status-note">Compatibility warning: ${esc(warnings[0])}</p>`
      : "";
    root.innerHTML =
      `<div class="model-live-row"><span class="model-live-badge">Live</span></div>` +
      `<div class="model-status-grid">` +
      `<article class="model-mini-card"><small>Training Decks</small><strong>${esc(status.trainingDeckCount || 0)}</strong></article>` +
      `<article class="model-mini-card"><small>Win Conditions</small><strong>${esc(summary.selectedWinConditionCount || status.selectedWinConditionCount || status.winConditionCount || 0)}</strong></article>` +
      `<article class="model-mini-card"><small>Synergy Clusters</small><strong>${esc(summary.selectedSynergyClusterCount || status.selectedSynergyClusterCount || status.synergyClusterCount || 0)}</strong></article>` +
      `<article class="model-mini-card"><small>Shells / Archetypes</small><strong>${esc((summary.uniqueShellCount || status.uniqueShellCount || 0) + " / " + (summary.archetypeCount || status.archetypeCount || 0))}</strong></article>` +
      `</div>` +
      `<p class="model-status-note">Generated ${esc(generatedAt)} on ${esc(status.runtimeTorchDevice || "cpu")}.</p>` +
      warningNote +
      `<div class="model-mini-list">${sourceList}</div>`;
  }

  function renderModelObservationModels() {
    const root = document.getElementById("model-observation-models");
    if (!root) return;
    const rows = Array.isArray(state.modelObservation.models) ? state.modelObservation.models : [];
    if (!rows.length) {
      root.innerHTML = '<div class="deck-card-empty">No saved model versions yet. Snapshot the current production model or run training from this workspace.</div>';
      return;
    }
    const selected = modelObservationSelectedModel();
    if (selected) state.modelObservation.selectedModelId = String(selected.id || "");
    root.innerHTML = rows
      .map((row) => {
        const winCount = row.winConditionCount || 0;
        const synergyCount = row.synergyClusterCount || 0;
        const selectedClass = selected && String(selected.id || "") === String(row.id || "") ? "is-selected" : "";
        return (
          `<article class="model-version-card ${selectedClass}">` +
          `<div class="model-version-head">` +
          `<div>` +
          `<div class="model-version-title">${esc(row.label || row.id || "Saved Model")}</div>` +
          `<div class="model-version-meta">${esc(row.kind || "trained")} | ${esc(row.status || "ready")}${row.isProduction ? " | production" : ""}</div>` +
          `</div>` +
          `<div class="model-version-score"><span title="Win Conditions">${esc(winCount)} WC</span><span title="Synergy Clusters">${esc(synergyCount)} SC</span></div>` +
          `</div>` +
          `<div class="model-version-body">` +
          `<span>${esc(row.trainingDeckCount || 0)} decks</span>` +
          `<span>${esc(row.torchDevice || "-")}</span>` +
          `<span>${esc(row.createdAt ? new Date(row.createdAt).toLocaleString() : "-")}</span>` +
          `</div>` +
          `<div class="card-actions model-version-actions">` +
          `<button type="button" class="card-action-btn secondary" data-model-select="${escAttr(row.id)}">Inspect</button>` +
          `<button type="button" class="card-action-btn" data-model-promote="${escAttr(row.id)}"${row.isProduction ? " disabled" : ""}>${row.isProduction ? "Live" : "Promote"}</button>` +
          `</div>` +
          `</article>`
        );
      })
      .join("");
    Array.from(root.querySelectorAll("[data-model-select]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modelObservation.selectedModelId = String(btn.getAttribute("data-model-select") || "");
        renderModelObservationDetail();
        renderModelObservationModels();
      });
    });
    Array.from(root.querySelectorAll("[data-model-promote]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const modelId = String(btn.getAttribute("data-model-promote") || "");
        if (!modelId) return;
        showConfirmModal({
          title: "Promote Model",
          body: "Promote this saved model to production? The current production model will be replaced.",
          confirmLabel: "Promote",
          onConfirm: async () => {
            try {
              await promoteModelObservationModel(modelId);
            } catch (err) {
              setStatus(err.message || "Could not promote saved model.", true);
            }
          }
        });
      });
    });
  }

  function clampNumber(value, minValue, maxValue) {
    const num = Number(value);
    if (!Number.isFinite(num)) return minValue;
    return Math.max(minValue, Math.min(maxValue, num));
  }

  function modelGraphTypeLabel(kind) {
    if (kind === "win") return "Win Condition";
    if (kind === "shell") return "Shell";
    if (kind === "archetype") return "Archetype";
    if (kind === "synergy") return "Synergy Cluster";
    if (kind === "card") return "Card";
    return "Feature";
  }

  function modelGraphTypeRank(kind) {
    if (kind === "archetype") return 0;
    if (kind === "win") return 1;
    if (kind === "synergy") return 2;
    if (kind === "shell") return 3;
    if (kind === "card") return 4;
    return 5;
  }

  function modelGraphNodeId(kind, rawId) {
    return `${String(kind || "feature").trim()}:${String(rawId || "").trim()}`;
  }

  function addModelGraphNode(nodesById, node) {
    if (!node || !node.id) return null;
    const next = {
      id: String(node.id),
      type: String(node.type || "feature"),
      label: String(node.label || "Unnamed Feature"),
      subtitle: String(node.subtitle || ""),
      metaLine: String(node.metaLine || ""),
      description: String(node.description || ""),
      imageUrl: String(node.imageUrl || ""),
      imageFallback: String(node.imageFallback || ""),
      importance: Number(node.importance || 1),
      searchText: normalizeCardKey(
        [
          node.label || "",
          node.subtitle || "",
          node.metaLine || "",
          node.description || "",
          ...(Array.isArray(node.featureCards) ? node.featureCards : [])
        ].join(" ")
      ),
      featureCards: Array.isArray(node.featureCards) ? Array.from(new Set(node.featureCards.map((value) => canonicalTitle(value)).filter(Boolean))) : [],
      degree: 0,
      neighborIds: [],
      raw: node.raw || null
    };
    const existing = nodesById[next.id];
    if (!existing) {
      nodesById[next.id] = next;
      return next;
    }
    existing.importance = Math.max(existing.importance, next.importance);
    if (!existing.subtitle && next.subtitle) existing.subtitle = next.subtitle;
    if (!existing.metaLine && next.metaLine) existing.metaLine = next.metaLine;
    if (!existing.description && next.description) existing.description = next.description;
    if (!existing.imageUrl && next.imageUrl) existing.imageUrl = next.imageUrl;
    if (!existing.imageFallback && next.imageFallback) existing.imageFallback = next.imageFallback;
    if (!existing.raw && next.raw) existing.raw = next.raw;
    const mergedCards = new Set([...(existing.featureCards || []), ...(next.featureCards || [])]);
    existing.featureCards = Array.from(mergedCards).slice(0, 10);
    existing.searchText = normalizeCardKey(`${existing.searchText || ""} ${next.searchText || ""}`);
    return existing;
  }

  function addModelGraphEdge(edges, edgeMap, leftId, rightId, kind, weight) {
    const sourceId = String(leftId || "").trim();
    const targetId = String(rightId || "").trim();
    if (!sourceId || !targetId || sourceId === targetId) return;
    const ordered = sourceId < targetId ? [sourceId, targetId] : [targetId, sourceId];
    const key = `${ordered[0]}|${ordered[1]}`;
    const numericWeight = Math.max(0.2, Number(weight || 1));
    const existing = edgeMap[key];
    if (existing) {
      existing.weight = Math.max(existing.weight, numericWeight);
      return;
    }
    const edge = {
      id: key,
      sourceId: ordered[0],
      targetId: ordered[1],
      kind: String(kind || "link"),
      weight: numericWeight
    };
    edgeMap[key] = edge;
    edges.push(edge);
  }

  function buildModelObservationGraph(observation) {
    const nodesById = {};
    const edges = [];
    const edgeMap = {};
    const cardRefs = {};

    const allWins = Array.isArray(observation.winConditions) ? observation.winConditions : [];
    const allShells = Array.isArray(observation.shells) ? observation.shells : [];
    const allArchetypes = Array.isArray(observation.archetypes) ? observation.archetypes : [];
    const allSynergy = Array.isArray(observation.synergyClusters) ? observation.synergyClusters : [];

    const winRowsById = {};
    const shellRowsById = {};
    const archetypeRowsById = {};
    const synergyRowsById = {};

    allWins.forEach((row) => {
      winRowsById[String(row && row.id != null ? row.id : "")] = row;
    });
    allShells.forEach((row) => {
      shellRowsById[String((row && row.shellId) || "")] = row;
    });
    allArchetypes.forEach((row) => {
      archetypeRowsById[String((row && row.archetypeId) || "")] = row;
    });
    allSynergy.forEach((row) => {
      synergyRowsById[String(row && row.id != null ? row.id : "")] = row;
    });

    function collectFeatureCards(values, limit) {
      return Array.from(
        new Set(
          (Array.isArray(values) ? values : [])
            .map((value) => canonicalTitle(value))
            .filter(Boolean)
        )
      ).slice(0, Math.max(1, Number(limit) || 1));
    }

    function rememberCard(rawTitle, featureId, weight, reason) {
      const title = canonicalTitle(rawTitle);
      const nodeId = String(featureId || "").trim();
      if (!title || !nodeId) return;
      const key = normalizeCardKey(title);
      if (!key) return;
      const entry = cardRefs[key] || {
        key,
        title,
        weight: 0,
        refs: {},
        reasons: {},
        imageUrl: "",
        card: null
      };
      const info = entry.card || lookupCard(title);
      entry.card = info || entry.card;
      entry.imageUrl = entry.imageUrl || (info && info.imageUrl ? info.imageUrl : "");
      entry.weight += Math.max(0.2, Number(weight || 0.2));
      entry.refs[nodeId] = (entry.refs[nodeId] || 0) + Math.max(0.2, Number(weight || 0.2));
      entry.reasons[reason || "feature"] = (entry.reasons[reason || "feature"] || 0) + 1;
      cardRefs[key] = entry;
    }

    function createWinNode(row) {
      if (!row) return null;
      const wcId = String(row.id != null ? row.id : "").trim();
      if (!wcId) return null;
      const topCards = collectFeatureCards(row.topCards || [], 6);
      const sampleDeckCount = Number(row.sampleDeckCount || 0);
      const shellCoverageCount = Number(row.shellCoverageCount || 0);
      const topTokens = Array.isArray(row.topEffectTokens) ? row.topEffectTokens.filter(Boolean).slice(0, 3) : [];
      const exemplarTitle = topCards[0] || row.label || `WC ${wcId}`;
      const exemplarCard = lookupCard(exemplarTitle);
      const node = addModelGraphNode(nodesById, {
        id: modelGraphNodeId("win", wcId),
        type: "win",
        label: row.label || `WC ${wcId}`,
        subtitle: topTokens.join(" • ") || topCards.slice(0, 2).join(" • ") || "Latent objective cluster",
        metaLine: `${sampleDeckCount} decks • ${shellCoverageCount} shells`,
        description: topCards.length ? `Key cards: ${topCards.slice(0, 4).join(" • ")}` : "No top cards recorded.",
        imageUrl: exemplarCard && exemplarCard.imageUrl ? exemplarCard.imageUrl : "",
        imageFallback: cardBackFor(exemplarTitle),
        importance: 3 + sampleDeckCount / 120 + shellCoverageCount / 10,
        featureCards: topCards,
        raw: row
      });
      topCards.forEach((title, index) => rememberCard(title, node.id, 3.8 - index * 0.55, "win"));
      return node;
    }

    function createShellNode(row) {
      if (!row) return null;
      const shellId = String(row.shellId || "").trim();
      if (!shellId) return null;
      const featuredCards = collectFeatureCards([row.legendTitle, row.chosenChampionTitle], 4);
      const leadTitle = featuredCards[0] || row.shellLabel || shellId;
      const leadCard = lookupCard(leadTitle);
      const domains = Array.isArray(row.legendDomains) ? row.legendDomains.filter(Boolean) : [];
      const node = addModelGraphNode(nodesById, {
        id: modelGraphNodeId("shell", shellId),
        type: "shell",
        label: row.shellLabel || "Unknown Shell",
        subtitle: featuredCards.join(" + ") || "No legend pair recorded",
        metaLine: `${Number(row.trainingDeckCount || 0)} decks • build ${Number(row.buildabilityPrior || 0).toFixed(2)}`,
        description: domains.length ? `Domains: ${domains.join(" • ")}` : "No domain tags recorded.",
        imageUrl: leadCard && leadCard.imageUrl ? leadCard.imageUrl : "",
        imageFallback: cardBackFor(leadTitle),
        importance: 3 + Number(row.competitivePrior || 0) * 1.4 + Number(row.buildabilityPrior || 0) * 1.2,
        featureCards: featuredCards,
        raw: row
      });
      featuredCards.forEach((title, index) => rememberCard(title, node.id, 3.2 - index * 0.45, "shell"));
      return node;
    }

    function createSynergyNode(row) {
      if (!row) return null;
      const clusterId = String(row.id != null ? row.id : "").trim();
      if (!clusterId) return null;
      const topCards = collectFeatureCards(row.topCards || [], 6);
      const exemplarTitle = topCards[0] || row.label || `Cluster ${clusterId}`;
      const exemplarCard = lookupCard(exemplarTitle);
      const node = addModelGraphNode(nodesById, {
        id: modelGraphNodeId("synergy", clusterId),
        type: "synergy",
        label: row.label || `Cluster ${clusterId}`,
        subtitle: topCards.slice(0, 2).join(" • ") || "Replacement neighborhood",
        metaLine: `comp ${Number(row.avgCompetitiveScore || 0).toFixed(1)}`,
        description: topCards.length ? `Common members: ${topCards.slice(0, 4).join(" • ")}` : "No top cards recorded.",
        imageUrl: exemplarCard && exemplarCard.imageUrl ? exemplarCard.imageUrl : "",
        imageFallback: cardBackFor(exemplarTitle),
        importance: 3 + Number(row.avgCompetitiveScore || 0) / 10 + topCards.length * 0.2,
        featureCards: topCards,
        raw: row
      });
      topCards.forEach((title, index) => rememberCard(title, node.id, 3.1 - index * 0.42, "synergy"));
      return node;
    }

    function createArchetypeNode(row) {
      if (!row) return null;
      const archetypeId = String(row.archetypeId || "").trim();
      if (!archetypeId) return null;
      const topCore = collectFeatureCards(row.topCoreCards || [], 4);
      const topFlex = collectFeatureCards(row.topFlexCards || [], 3);
      const featuredCards = collectFeatureCards(
        [row.legendTitle, row.chosenChampionTitle, ...topCore, ...topFlex],
        8
      );
      const exemplarTitle = topCore[0] || featuredCards[0] || row.archetypeName || archetypeId;
      const exemplarCard = lookupCard(exemplarTitle);
      const node = addModelGraphNode(nodesById, {
        id: modelGraphNodeId("archetype", archetypeId),
        type: "archetype",
        label: row.archetypeName || "Unnamed Archetype",
        subtitle: topCore.slice(0, 2).join(" • ") || featuredCards.slice(0, 2).join(" • ") || "Prototype family",
        metaLine: `build ${Number(row.buildabilityPrior || 0).toFixed(2)} • conf ${Number(row.confidence || 0).toFixed(2)}`,
        description: topCore.length ? `Core: ${topCore.join(" • ")}` : "No core cards recorded.",
        imageUrl: exemplarCard && exemplarCard.imageUrl ? exemplarCard.imageUrl : "",
        imageFallback: cardBackFor(exemplarTitle),
        importance:
          4 +
          Number(row.competitivePrior || 0) * 1.7 +
          Number(row.buildabilityPrior || 0) * 1.2 +
          Number(row.confidence || 0) * 1.8,
        featureCards: featuredCards,
        raw: row
      });
      featuredCards.forEach((title, index) => rememberCard(title, node.id, 4.2 - index * 0.45, index < topCore.length ? "core" : "archetype"));
      return node;
    }

    function ensureWinNode(rawId) {
      const id = String(rawId != null ? rawId : "").trim();
      if (!id) return null;
      const nodeId = modelGraphNodeId("win", id);
      return nodesById[nodeId] || createWinNode(winRowsById[id]);
    }

    function ensureShellNode(rawId) {
      const id = String(rawId || "").trim();
      if (!id) return null;
      const nodeId = modelGraphNodeId("shell", id);
      return nodesById[nodeId] || createShellNode(shellRowsById[id]);
    }

    function ensureSynergyNode(rawId) {
      const id = String(rawId != null ? rawId : "").trim();
      if (!id) return null;
      const nodeId = modelGraphNodeId("synergy", id);
      return nodesById[nodeId] || createSynergyNode(synergyRowsById[id]);
    }

    const winRows = allWins
      .slice()
      .sort(
        (left, right) =>
          Number(right.sampleDeckCount || 0) - Number(left.sampleDeckCount || 0) ||
          Number(right.shellCoverageCount || 0) - Number(left.shellCoverageCount || 0) ||
          String(right.label || "").localeCompare(String(left.label || ""))
      )
      .slice(0, 10);
    const shellRows = allShells
      .slice()
      .sort(
        (left, right) =>
          Number(right.competitivePrior || 0) - Number(left.competitivePrior || 0) ||
          Number(right.buildabilityPrior || 0) - Number(left.buildabilityPrior || 0) ||
          String(left.shellLabel || "").localeCompare(String(right.shellLabel || ""))
      )
      .slice(0, 10);
    const synergyRows = allSynergy
      .slice()
      .sort(
        (left, right) =>
          Number(right.avgCompetitiveScore || 0) - Number(left.avgCompetitiveScore || 0) ||
          String(left.label || "").localeCompare(String(right.label || ""))
      )
      .slice(0, 10);
    const archetypeRows = allArchetypes
      .slice()
      .sort(
        (left, right) =>
          Number(right.competitivePrior || 0) - Number(left.competitivePrior || 0) ||
          Number(right.buildabilityPrior || 0) - Number(left.buildabilityPrior || 0) ||
          Number(right.confidence || 0) - Number(left.confidence || 0) ||
          String(left.archetypeName || "").localeCompare(String(right.archetypeName || ""))
      )
      .slice(0, 18);

    winRows.forEach((row) => createWinNode(row));
    shellRows.forEach((row) => createShellNode(row));
    synergyRows.forEach((row) => createSynergyNode(row));

    archetypeRows.forEach((row) => {
      const archetypeNode = createArchetypeNode(row);
      if (!archetypeNode) return;
      const shellNode = ensureShellNode(row.shellId);
      if (shellNode) addModelGraphEdge(edges, edgeMap, archetypeNode.id, shellNode.id, "shell", 2.4);
      const winNode = ensureWinNode(row.winConditionId);
      if (winNode) addModelGraphEdge(edges, edgeMap, archetypeNode.id, winNode.id, "win", 2.8);
      const synergyIds = Array.isArray(row.synergyClusterIds) ? row.synergyClusterIds : [];
      synergyIds.slice(0, 3).forEach((clusterId, index) => {
        const synergyNode = ensureSynergyNode(clusterId);
        if (synergyNode) {
          addModelGraphEdge(edges, edgeMap, archetypeNode.id, synergyNode.id, "synergy", 2.3 - index * 0.3);
        }
      });
    });

    Object.values(cardRefs)
      .sort(
        (left, right) =>
          Number(right.weight || 0) - Number(left.weight || 0) ||
          Object.keys(right.refs || {}).length - Object.keys(left.refs || {}).length ||
          String(left.title || "").localeCompare(String(right.title || ""))
      )
      .slice(0, 24)
      .forEach((entry) => {
        const card = entry.card || lookupCard(entry.title);
        const cardId = modelGraphNodeId("card", entry.key);
        addModelGraphNode(nodesById, {
          id: cardId,
          type: "card",
          label: entry.title,
          subtitle: [
            normalizeRarityLabel(card && card.rarity ? card.rarity : ""),
            normalizeSetLabel(card && card.set ? card.set : "")
          ]
            .filter(Boolean)
            .join(" • "),
          metaLine: card ? cardMetaLine(card) || cardStatsLine(card) : "Catalog card",
          description: truncateText((card && card.effect) || "Model-linked feature card.", 180),
          imageUrl: card && card.imageUrl ? card.imageUrl : entry.imageUrl || "",
          imageFallback: cardBackFor(entry.title),
          importance: 3 + Number(entry.weight || 0) * 0.3 + Object.keys(entry.refs || {}).length * 0.35,
          featureCards: [entry.title],
          raw: card || entry
        });
        Object.keys(entry.refs || {}).forEach((featureId) => {
          if (!nodesById[featureId]) return;
          addModelGraphEdge(edges, edgeMap, cardId, featureId, "card", 0.8 + Number(entry.refs[featureId] || 0) * 0.16);
        });
      });

    edges.forEach((edge) => {
      const source = nodesById[edge.sourceId];
      const target = nodesById[edge.targetId];
      if (!source || !target) return;
      source.degree += 1;
      target.degree += 1;
      source.neighborIds.push(target.id);
      target.neighborIds.push(source.id);
    });

    const counts = { all: 0, win: 0, shell: 0, archetype: 0, synergy: 0, card: 0 };
    const nodes = Object.values(nodesById)
      .map((node) => ({
        ...node,
        neighborIds: Array.from(new Set(node.neighborIds))
      }))
      .sort(
        (left, right) =>
          modelGraphTypeRank(left.type) - modelGraphTypeRank(right.type) ||
          Number(right.importance || 0) - Number(left.importance || 0) ||
          String(left.label || "").localeCompare(String(right.label || ""))
      );
    nodes.forEach((node) => {
      counts.all += 1;
      counts[node.type] = (counts[node.type] || 0) + 1;
    });
    return {
      nodes,
      edges,
      nodesById,
      counts
    };
  }

  function filterModelObservationGraph(graph, options) {
    const nodeList = Array.isArray(graph && graph.nodes) ? graph.nodes : [];
    const nodeById = graph && graph.nodesById ? graph.nodesById : {};
    const visibleIds = new Set(nodeList.map((node) => node.id));
    const focus = String((options && options.focus) || "all").trim().toLowerCase();
    const search = normalizeCardKey(String((options && options.search) || "").trim());
    let selectedId = String((options && options.selectedId) || "").trim();

    if (focus && focus !== "all") {
      const expanded = new Set();
      nodeList
        .filter((node) => node.type === focus)
        .forEach((node) => {
          expanded.add(node.id);
          (node.neighborIds || []).slice(0, 16).forEach((neighborId) => expanded.add(neighborId));
        });
      visibleIds.clear();
      expanded.forEach((id) => visibleIds.add(id));
    }

    let matchedCount = 0;
    if (search) {
      const expanded = new Set();
      nodeList
        .filter((node) => (node.searchText || "").indexOf(search) >= 0)
        .forEach((node) => {
          matchedCount += 1;
          expanded.add(node.id);
          (node.neighborIds || []).slice(0, 14).forEach((neighborId) => expanded.add(neighborId));
        });
      if (!expanded.size) {
        visibleIds.clear();
      } else {
        Array.from(visibleIds).forEach((id) => {
          if (!expanded.has(id)) visibleIds.delete(id);
        });
      }
    }

    if (!visibleIds.has(selectedId)) {
      selectedId = "";
    }
    if (!selectedId && visibleIds.size) {
      const fallback = nodeList.find((node) => visibleIds.has(node.id));
      selectedId = fallback ? fallback.id : "";
    }

    const emphasisIds = new Set();
    if (selectedId && nodeById[selectedId]) {
      emphasisIds.add(selectedId);
      (nodeById[selectedId].neighborIds || []).forEach((neighborId) => {
        if (visibleIds.has(neighborId)) emphasisIds.add(neighborId);
      });
    } else {
      visibleIds.forEach((id) => emphasisIds.add(id));
    }

    const nodes = nodeList
      .filter((node) => visibleIds.has(node.id))
      .map((node) => ({
        ...node,
        isSelected: node.id === selectedId,
        isDimmed: Boolean(selectedId) && !emphasisIds.has(node.id)
      }));
    const edges = (Array.isArray(graph && graph.edges) ? graph.edges : [])
      .filter((edge) => visibleIds.has(edge.sourceId) && visibleIds.has(edge.targetId))
      .map((edge) => ({
        ...edge,
        isDimmed: Boolean(selectedId) && !(emphasisIds.has(edge.sourceId) && emphasisIds.has(edge.targetId))
      }));
    return {
      nodes,
      edges,
      selectedId,
      selectedNode: selectedId && nodeById[selectedId] ? nodeById[selectedId] : null,
      matchedCount,
      visibleIds
    };
  }

  function resolveModelGraphCollisions(nodes, width, height, passes, immovableIds) {
    const rows = Array.isArray(nodes) ? nodes : [];
    const fixedIds = immovableIds instanceof Set ? immovableIds : new Set();
    const maxPasses = Math.max(1, Number(passes || 1));
    for (let pass = 0; pass < maxPasses; pass += 1) {
      let moved = false;
      for (let leftIndex = 0; leftIndex < rows.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < rows.length; rightIndex += 1) {
          const left = rows[leftIndex];
          const right = rows[rightIndex];
          const padding = left.type === "card" && right.type === "card" ? 52 : 68;
          const dx = right.x - left.x;
          const dy = right.y - left.y;
          const safeDx = Math.abs(dx) > 0.001 ? dx : (hashString(`${left.id}:${right.id}:dx`) % 2 ? 1 : -1);
          const safeDy = Math.abs(dy) > 0.001 ? dy : (hashString(`${left.id}:${right.id}:dy`) % 2 ? 1 : -1);
          const requiredX = (left.width + right.width) / 2 + padding;
          const requiredY = (left.height + right.height) / 2 + padding * 0.84;
          if (Math.abs(dx) >= requiredX || Math.abs(dy) >= requiredY) continue;
          const overlapX = requiredX - Math.abs(dx);
          const overlapY = requiredY - Math.abs(dy);
          const leftLocked = Boolean(left.locked) || fixedIds.has(left.id);
          const rightLocked = Boolean(right.locked) || fixedIds.has(right.id);
          if (leftLocked && rightLocked) continue;
          if (overlapX < overlapY) {
            const push = (safeDx >= 0 ? 1 : -1) * (overlapX + 3.2);
            if (leftLocked) right.x += push;
            else if (rightLocked) left.x -= push;
            else {
              left.x -= push / 2;
              right.x += push / 2;
            }
          } else {
            const push = (safeDy >= 0 ? 1 : -1) * (overlapY + 3.2);
            if (leftLocked) right.y += push;
            else if (rightLocked) left.y -= push;
            else {
              left.y -= push / 2;
              right.y += push / 2;
            }
          }
          moved = true;
        }
      }
      rows.forEach((node) => {
        node.x = clampNumber(node.x, node.width / 2 + 36, width - node.width / 2 - 36);
        node.y = clampNumber(node.y, node.height / 2 + 32, height - node.height / 2 - 32);
      });
      if (!moved) break;
    }
  }

  function refreshModelGraphEdgeGeometry(edges, nodeById) {
    return (Array.isArray(edges) ? edges : []).map((edge) => {
      const source = nodeById[edge.sourceId];
      const target = nodeById[edge.targetId];
      return {
        ...edge,
        x1: source ? source.x : 0,
        y1: source ? source.y : 0,
        x2: target ? target.x : 0,
        y2: target ? target.y : 0
      };
    });
  }

  function layoutModelObservationGraph(nodes, edges, selectedId, options) {
    const positionOverrides = options && typeof options.positions === "object" ? options.positions : {};
    const pinnedIds = options && typeof options.pinnedIds === "object" ? options.pinnedIds : {};
    const width = clampNumber(1460 + nodes.length * 18, 1580, 2360);
    const height = clampNumber(940 + nodes.length * 13, 1040, 1680);
    const centerX = width / 2;
    const centerY = height / 2;
    const baseRadius = Math.min(width, height) * 0.215;
    const typeAngles = {
      win: -2.28,
      shell: -0.72,
      synergy: 2.28
    };
    const typeSpans = {
      win: 1.04,
      shell: 0.98,
      synergy: 0.98
    };
    const typeBuckets = {
      win: [],
      shell: [],
      archetype: [],
      synergy: [],
      card: []
    };
    const positioned = nodes.map((node) => {
      const dims =
        node.type === "card"
          ? { width: 96, height: 132 }
          : node.type === "archetype"
            ? { width: 228, height: 96 }
            : { width: 192, height: 86 };
      const override = positionOverrides[node.id];
      const hasOverride =
        override &&
        Number.isFinite(Number(override.x)) &&
        Number.isFinite(Number(override.y));
      const entry = {
        ...node,
        width: dims.width,
        height: dims.height,
        radius: Math.sqrt(dims.width * dims.width + dims.height * dims.height) / 2,
        x: hasOverride ? Number(override.x) : centerX,
        y: hasOverride ? Number(override.y) : centerY,
        vx: 0,
        vy: 0,
        anchorX: hasOverride ? Number(override.x) : centerX,
        anchorY: hasOverride ? Number(override.y) : centerY,
        locked: Boolean(pinnedIds[node.id])
      };
      if (typeBuckets[entry.type]) typeBuckets[entry.type].push(entry);
      return entry;
    });

    function jitter(node, salt, amplitude) {
      const raw = hashString(`${salt}:${node.id}`);
      return ((((raw % 2000) / 1999) - 0.5) * amplitude);
    }

    function positionBucket(bucket, centerAngle, span, radius, ringStride) {
      bucket.forEach((node, index) => {
        if (positionOverrides[node.id]) return;
        const ratio = bucket.length <= 1 ? 0.5 : index / (bucket.length - 1);
        const angle = centerAngle - span / 2 + span * ratio + jitter(node, "angle", 0.18);
        const ring = radius + (index % 3) * ringStride + jitter(node, "radius", ringStride * 0.75);
        node.anchorX = centerX + Math.cos(angle) * ring;
        node.anchorY = centerY + Math.sin(angle) * ring;
        node.x = node.anchorX;
        node.y = node.anchorY;
      });
    }

    positionBucket(typeBuckets.win, typeAngles.win, typeSpans.win, baseRadius * 1.82, 30);
    positionBucket(typeBuckets.shell, typeAngles.shell, typeSpans.shell, baseRadius * 1.94, 30);
    positionBucket(typeBuckets.synergy, typeAngles.synergy, typeSpans.synergy, baseRadius * 1.96, 30);

    typeBuckets.archetype.forEach((node, index) => {
      if (positionOverrides[node.id]) return;
      const ratio = typeBuckets.archetype.length <= 1 ? 0.5 : index / typeBuckets.archetype.length;
      const angle = -Math.PI / 2 + Math.PI * 2 * ratio + jitter(node, "arch-angle", 0.24);
      const ring = baseRadius * 1.08 + (index % 4) * 28 + jitter(node, "arch-radius", 22);
      node.anchorX = centerX + Math.cos(angle) * ring;
      node.anchorY = centerY + Math.sin(angle) * ring;
      node.x = node.anchorX;
      node.y = node.anchorY;
    });

    typeBuckets.card.forEach((node, index) => {
      if (positionOverrides[node.id]) return;
      const ratio = typeBuckets.card.length <= 1 ? 0.5 : index / typeBuckets.card.length;
      const angle = -Math.PI / 2 + Math.PI * 2 * ratio + jitter(node, "card-angle", 0.2);
      const ring = baseRadius * 3.18 + (index % 5) * 36 + jitter(node, "card-radius", 32);
      node.anchorX = centerX + Math.cos(angle) * ring;
      node.anchorY = centerY + Math.sin(angle) * ring;
      node.x = node.anchorX;
      node.y = node.anchorY;
    });

    const nodeById = {};
    positioned.forEach((node) => {
      nodeById[node.id] = node;
    });

    for (let iteration = 0; iteration < 156; iteration += 1) {
      const forces = {};
      positioned.forEach((node) => {
        forces[node.id] = {
          x: node.locked ? 0 : (node.anchorX - node.x) * 0.038,
          y: node.locked ? 0 : (node.anchorY - node.y) * 0.038
        };
        if (!node.locked && selectedId && node.id === selectedId) {
          forces[node.id].x += (centerX - node.x) * 0.09;
          forces[node.id].y += (centerY - node.y) * 0.09;
        }
      });

      for (let leftIndex = 0; leftIndex < positioned.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < positioned.length; rightIndex += 1) {
          const left = positioned[leftIndex];
          const right = positioned[rightIndex];
          const dx = right.x - left.x;
          const dy = right.y - left.y;
          const distSq = Math.max(1, dx * dx + dy * dy);
          const dist = Math.sqrt(distSq);
          const nx = dx / dist;
          const ny = dy / dist;
          const minGap = left.radius + right.radius + (left.type === "card" && right.type === "card" ? 58 : 80);
          const repulsion = dist < minGap ? (minGap - dist) * 0.38 : 9800 / distSq;
          const leftLocked = Boolean(left.locked);
          const rightLocked = Boolean(right.locked);
          if (leftLocked && rightLocked) continue;
          if (!leftLocked && !rightLocked) {
            forces[left.id].x -= nx * repulsion;
            forces[left.id].y -= ny * repulsion;
            forces[right.id].x += nx * repulsion;
            forces[right.id].y += ny * repulsion;
          } else if (leftLocked) {
            forces[right.id].x += nx * repulsion * 1.75;
            forces[right.id].y += ny * repulsion * 1.75;
          } else {
            forces[left.id].x -= nx * repulsion * 1.75;
            forces[left.id].y -= ny * repulsion * 1.75;
          }
        }
      }

      edges.forEach((edge) => {
        const source = nodeById[edge.sourceId];
        const target = nodeById[edge.targetId];
        if (!source || !target) return;
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const desired =
          source.type === "card" || target.type === "card"
            ? 242
            : source.type === "archetype" || target.type === "archetype"
              ? 294
              : 332;
        const pull = (dist - desired) * 0.018 * Math.max(0.38, Number(edge.weight || 1));
        const nx = dx / dist;
        const ny = dy / dist;
        if (!source.locked && !target.locked) {
          forces[source.id].x += nx * pull;
          forces[source.id].y += ny * pull;
          forces[target.id].x -= nx * pull;
          forces[target.id].y -= ny * pull;
        } else if (source.locked && !target.locked) {
          forces[target.id].x -= nx * pull * 1.8;
          forces[target.id].y -= ny * pull * 1.8;
        } else if (!source.locked && target.locked) {
          forces[source.id].x += nx * pull * 1.8;
          forces[source.id].y += ny * pull * 1.8;
        }
      });

      positioned.forEach((node) => {
        if (node.locked) {
          node.x = clampNumber(node.x, node.width / 2 + 36, width - node.width / 2 - 36);
          node.y = clampNumber(node.y, node.height / 2 + 32, height - node.height / 2 - 32);
          node.vx = 0;
          node.vy = 0;
          return;
        }
        node.vx = (node.vx + forces[node.id].x) * 0.76;
        node.vy = (node.vy + forces[node.id].y) * 0.76;
        node.x = clampNumber(node.x + node.vx, node.width / 2 + 36, width - node.width / 2 - 36);
        node.y = clampNumber(node.y + node.vy, node.height / 2 + 32, height - node.height / 2 - 32);
      });

      resolveModelGraphCollisions(positioned, width, height, 3);
    }

    resolveModelGraphCollisions(positioned, width, height, 144);
    positioned.forEach((node) => {
      nodeById[node.id] = node;
    });
    return {
      width,
      height,
      nodes: positioned,
      nodeById,
      edges: refreshModelGraphEdgeGeometry(edges, nodeById),
      selectedId: selectedId || ""
    };
  }

  function renderModelObservationGraphInspector(context) {
    const selectedNode = context && context.selectedNode ? context.selectedNode : null;
    if (!selectedNode) {
      return '<div class="deck-card-empty">Select a node to inspect its discovered neighborhood.</div>';
    }
    const nodeById = context && context.nodeById ? context.nodeById : {};
    const visibleIds = context && context.visibleIds ? context.visibleIds : new Set();
    const relatedNodes = (selectedNode.neighborIds || [])
      .map((id) => nodeById[id])
      .filter((node) => node && (!visibleIds.size || visibleIds.has(node.id)))
      .sort(
        (left, right) =>
          modelGraphTypeRank(left.type) - modelGraphTypeRank(right.type) ||
          Number(right.importance || 0) - Number(left.importance || 0) ||
          String(left.label || "").localeCompare(String(right.label || ""))
      )
      .slice(0, 12);
    const featureCards = Array.from(new Set((selectedNode.featureCards || []).map((title) => canonicalTitle(title)).filter(Boolean))).slice(0, 8);
    const raw = selectedNode.raw && typeof selectedNode.raw === "object" ? selectedNode.raw : {};
    const stats = [
      ["Type", modelGraphTypeLabel(selectedNode.type)],
      ["Connections", selectedNode.degree || 0]
    ];
    if (selectedNode.type === "win") {
      stats.push(["Decks", Number(raw.sampleDeckCount || 0)]);
      stats.push(["Shells", Number(raw.shellCoverageCount || 0)]);
    } else if (selectedNode.type === "shell") {
      stats.push(["Decks", Number(raw.trainingDeckCount || 0)]);
      stats.push(["Build", Number(raw.buildabilityPrior || 0).toFixed(2)]);
    } else if (selectedNode.type === "archetype") {
      stats.push(["Build", Number(raw.buildabilityPrior || 0).toFixed(2)]);
      stats.push(["Confidence", Number(raw.confidence || 0).toFixed(2)]);
    } else if (selectedNode.type === "synergy") {
      stats.push(["Score", Number(raw.avgCompetitiveScore || 0).toFixed(1)]);
      stats.push(["Top Cards", featureCards.length]);
    } else if (selectedNode.type === "card") {
      const card = lookupCard(selectedNode.label);
      stats.push(["Set", normalizeSetLabel(card && card.set ? card.set : "-") || "-"]);
      stats.push(["Rarity", normalizeRarityLabel(card && card.rarity ? card.rarity : "-") || "-"]);
    }
    const heroImage = selectedNode.imageUrl || selectedNode.imageFallback || cardBackFor(selectedNode.label);
    const description = selectedNode.description || selectedNode.metaLine || "No detail recorded.";
    const cardTiles = featureCards.length
      ? featureCards
          .map((title) => {
            const card = lookupCard(title);
            const cardNodeId = modelGraphNodeId("card", normalizeCardKey(title));
            const previewImage = card && card.imageUrl ? card.imageUrl : cardBackFor(title);
            const targetNodeId = visibleIds.has(cardNodeId) ? cardNodeId : "";
            return (
              `<button type="button" class="model-graph-card-chip" data-model-graph-card="${escAttr(title)}" data-model-graph-target="${escAttr(targetNodeId)}" data-preview-title="${escAttr(title)}" data-preview-image="${escAttr(previewImage)}">` +
              `<img class="model-graph-card-chip-image ${card && card.imageUrl ? "" : "is-fallback"}" src="${escAttr(previewImage)}" alt="${escAttr(title)} artwork" data-fallback-src="${escAttr(cardBackFor(title))}" />` +
              `<span>${esc(truncateText(title, 22))}</span>` +
              `</button>`
            );
          })
          .join("")
      : '<div class="deck-card-empty">No representative cards recorded for this node.</div>';
    const related = relatedNodes.length
      ? relatedNodes
          .map(
            (node) =>
              `<button type="button" class="model-graph-related-chip" data-model-graph-node="${escAttr(node.id)}">` +
              `<small>${esc(modelGraphTypeLabel(node.type))}</small>` +
              `<strong>${esc(truncateText(node.label, 28))}</strong>` +
              `</button>`
          )
          .join("")
      : '<div class="deck-card-empty">No visible linked nodes in this filter.</div>';
    const openCardTitle =
      selectedNode.type === "card"
        ? selectedNode.label
        : featureCards[0] || "";
    return (
      `<div class="model-graph-inspector-card">` +
      `<div class="model-graph-inspector-hero">` +
      `<div class="model-graph-inspector-art">` +
      `<img class="model-graph-inspector-image ${selectedNode.imageUrl ? "" : "is-fallback"}" src="${escAttr(heroImage)}" alt="${escAttr(selectedNode.label)} artwork" data-fallback-src="${escAttr(selectedNode.imageFallback || cardBackFor(selectedNode.label))}" />` +
      `</div>` +
      `<div class="model-graph-inspector-copy">` +
      `<span class="model-graph-inspector-kicker">${esc(modelGraphTypeLabel(selectedNode.type))}</span>` +
      `<h4>${esc(selectedNode.label)}</h4>` +
      `<p>${esc(description)}</p>` +
      `<div class="model-graph-inspector-meta">${esc(selectedNode.metaLine || selectedNode.subtitle || "Latent feature node")}</div>` +
      `${openCardTitle ? `<button type="button" class="card-action-btn secondary" data-model-card-open="${escAttr(openCardTitle)}">Open Card</button>` : ""}` +
      `</div>` +
      `</div>` +
      `<div class="model-graph-stat-grid">` +
      stats
        .map(
          ([label, value]) =>
            `<div class="model-graph-stat"><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`
        )
        .join("") +
      `</div>` +
      `<div class="model-graph-inspector-section"><h4>Feature Cards</h4><div class="model-graph-card-strip">${cardTiles}</div></div>` +
      `<div class="model-graph-inspector-section"><h4>Connected Features</h4><div class="model-graph-related-list">${related}</div></div>` +
      `</div>`
    );
  }

  function normalizeModelGraphViewport(viewport) {
    const raw = viewport && typeof viewport === "object" ? viewport : {};
    return {
      x: Number.isFinite(Number(raw.x)) ? Number(raw.x) : 0,
      y: Number.isFinite(Number(raw.y)) ? Number(raw.y) : 0,
      scale: clampNumber(Number(raw.scale || 1), 0.42, 2.8),
      initialized: Boolean(raw.initialized)
    };
  }

  function computeModelGraphViewportFit(stage, sceneState) {
    const width = Number(sceneState && sceneState.width) || 1;
    const height = Number(sceneState && sceneState.height) || 1;
    const stageWidth = Math.max(1, Number(stage && stage.clientWidth) || 1);
    const stageHeight = Math.max(1, Number(stage && stage.clientHeight) || 1);
    const paddingX = 84;
    const paddingY = 76;
    const scale = clampNumber(
      Math.min((stageWidth - paddingX) / width, (stageHeight - paddingY) / height, 1.02),
      0.42,
      2.8
    );
    return {
      x: (stageWidth - width * scale) / 2,
      y: (stageHeight - height * scale) / 2,
      scale,
      initialized: true
    };
  }

  function constrainModelGraphViewport(stage, sceneState, viewport) {
    const next = normalizeModelGraphViewport(viewport);
    const width = Number(sceneState && sceneState.width) || 1;
    const height = Number(sceneState && sceneState.height) || 1;
    const stageWidth = Math.max(1, Number(stage && stage.clientWidth) || 1);
    const stageHeight = Math.max(1, Number(stage && stage.clientHeight) || 1);
    const scaledWidth = width * next.scale;
    const scaledHeight = height * next.scale;
    if (scaledWidth <= stageWidth - 36) {
      next.x = (stageWidth - scaledWidth) / 2;
    } else {
      next.x = clampNumber(next.x, stageWidth - scaledWidth - 96, 96);
    }
    if (scaledHeight <= stageHeight - 36) {
      next.y = (stageHeight - scaledHeight) / 2;
    } else {
      next.y = clampNumber(next.y, stageHeight - scaledHeight - 96, 96);
    }
    next.initialized = true;
    return next;
  }

  function applyModelGraphViewport(root, viewport) {
    const scene = root.querySelector(".model-graph-scene");
    if (scene) {
      scene.style.transformOrigin = "0 0";
      scene.style.transform = `translate(${viewport.x.toFixed(1)}px, ${viewport.y.toFixed(1)}px) scale(${viewport.scale.toFixed(3)})`;
    }
    const zoomLabel = root.querySelector("[data-model-graph-zoom-label]");
    if (zoomLabel) zoomLabel.textContent = `${Math.round(viewport.scale * 100)}%`;
  }

  function hydrateModelGraphSceneElements(root, sceneState) {
    sceneState.nodeElements = {};
    sceneState.edgeElements = {};
    Array.from(root.querySelectorAll("[data-model-graph-node]")).forEach((el) => {
      const id = String(el.getAttribute("data-model-graph-node") || "");
      if (id) sceneState.nodeElements[id] = el;
    });
    Array.from(root.querySelectorAll("[data-model-graph-edge]")).forEach((el) => {
      const id = String(el.getAttribute("data-model-graph-edge") || "");
      if (id) sceneState.edgeElements[id] = el;
    });
  }

  function updateModelGraphScene(root, sceneState) {
    if (!sceneState || !sceneState.nodeById) return;
    sceneState.nodes.forEach((node) => {
      const el = sceneState.nodeElements ? sceneState.nodeElements[node.id] : null;
      if (!el) return;
      el.style.left = `${(node.x - node.width / 2).toFixed(1)}px`;
      el.style.top = `${(node.y - node.height / 2).toFixed(1)}px`;
      el.style.width = `${node.width.toFixed(1)}px`;
      el.style.height = `${node.height.toFixed(1)}px`;
    });
    sceneState.edges = refreshModelGraphEdgeGeometry(sceneState.edges, sceneState.nodeById);
    sceneState.edges.forEach((edge) => {
      const el = sceneState.edgeElements ? sceneState.edgeElements[edge.id] : null;
      if (!el) return;
      el.setAttribute("x1", edge.x1.toFixed(1));
      el.setAttribute("y1", edge.y1.toFixed(1));
      el.setAttribute("x2", edge.x2.toFixed(1));
      el.setAttribute("y2", edge.y2.toFixed(1));
    });
  }

  function storeModelGraphPositions(sceneState) {
    const next = { ...(state.modelObservation.graphNodePositions || {}) };
    (sceneState && Array.isArray(sceneState.nodes) ? sceneState.nodes : []).forEach((node) => {
      next[node.id] = {
        x: Number(node.x.toFixed(2)),
        y: Number(node.y.toFixed(2))
      };
    });
    state.modelObservation.graphNodePositions = next;
  }

  function modelGraphClientToScene(stage, viewport, clientX, clientY) {
    const rect = stage.getBoundingClientRect();
    return {
      x: (clientX - rect.left - viewport.x) / viewport.scale,
      y: (clientY - rect.top - viewport.y) / viewport.scale
    };
  }

  function destroyActiveModelGraphRuntime() {
    if (!activeModelGraphRuntime) return;
    try {
      activeModelGraphRuntime.destroy();
    } catch (_err) {
      // no-op
    }
    activeModelGraphRuntime = null;
  }

  function modelGraphImmovableIds(sceneState, dragNodeId) {
    const ids = new Set();
    (sceneState && Array.isArray(sceneState.nodes) ? sceneState.nodes : []).forEach((node) => {
      if (node && node.locked) ids.add(node.id);
    });
    if (dragNodeId) ids.add(String(dragNodeId));
    return ids;
  }

  function stepModelGraphPhysics(sceneState, options) {
    if (!sceneState || !sceneState.nodeById) return { active: false, moved: false };
    const opts = options && typeof options === "object" ? options : {};
    const nodes = Array.isArray(sceneState.nodes) ? sceneState.nodes : [];
    const edges = Array.isArray(sceneState.edges) ? sceneState.edges : [];
    const nodeById = sceneState.nodeById || {};
    const draggedNodeId = String(opts.draggedNodeId || "").trim();
    const dtMs = clampNumber(Number(opts.dtMs || 16), 8, 40);
    const dtScale = dtMs / 16;
    const selectedId = String(opts.selectedId || sceneState.selectedId || "").trim();
    const centerX = Number(sceneState.width || 1) / 2;
    const centerY = Number(sceneState.height || 1) / 2;
    const immovableIds = modelGraphImmovableIds(sceneState, draggedNodeId);
    const forces = {};
    let maxSpeed = 0;
    let moved = false;

    nodes.forEach((node) => {
      const isDragged = node.id === draggedNodeId;
      const isFixed = immovableIds.has(node.id);
      const anchorStrength = isDragged ? 0 : node.type === "card" ? 0.0075 : 0.011;
      forces[node.id] = {
        x: isFixed ? 0 : (Number(node.anchorX || node.x) - Number(node.x || 0)) * anchorStrength,
        y: isFixed ? 0 : (Number(node.anchorY || node.y) - Number(node.y || 0)) * anchorStrength
      };
      if (!isFixed && selectedId && node.id === selectedId) {
        forces[node.id].x += (centerX - node.x) * 0.015;
        forces[node.id].y += (centerY - node.y) * 0.015;
      }
    });

    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        const dx = right.x - left.x;
        const dy = right.y - left.y;
        const distSq = Math.max(1, dx * dx + dy * dy);
        const dist = Math.sqrt(distSq);
        const nx = dx / dist;
        const ny = dy / dist;
        const minGap = left.radius + right.radius + (left.type === "card" && right.type === "card" ? 54 : 74);
        const repulsion = dist < minGap ? (minGap - dist) * 0.22 : 7200 / distSq;
        const leftFixed = immovableIds.has(left.id);
        const rightFixed = immovableIds.has(right.id);
        if (leftFixed && rightFixed) continue;
        if (!leftFixed && !rightFixed) {
          forces[left.id].x -= nx * repulsion;
          forces[left.id].y -= ny * repulsion;
          forces[right.id].x += nx * repulsion;
          forces[right.id].y += ny * repulsion;
        } else if (leftFixed) {
          forces[right.id].x += nx * repulsion * 1.5;
          forces[right.id].y += ny * repulsion * 1.5;
        } else {
          forces[left.id].x -= nx * repulsion * 1.5;
          forces[left.id].y -= ny * repulsion * 1.5;
        }
      }
    }

    edges.forEach((edge) => {
      const source = nodeById[edge.sourceId];
      const target = nodeById[edge.targetId];
      if (!source || !target) return;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const desired =
        source.type === "card" || target.type === "card"
          ? 234
          : source.type === "archetype" || target.type === "archetype"
            ? 286
            : 324;
      const pull = (dist - desired) * 0.009 * Math.max(0.4, Number(edge.weight || 1));
      const nx = dx / dist;
      const ny = dy / dist;
      const sourceFixed = immovableIds.has(source.id);
      const targetFixed = immovableIds.has(target.id);
      if (sourceFixed && targetFixed) return;
      if (!sourceFixed && !targetFixed) {
        forces[source.id].x += nx * pull;
        forces[source.id].y += ny * pull;
        forces[target.id].x -= nx * pull;
        forces[target.id].y -= ny * pull;
      } else if (sourceFixed) {
        forces[target.id].x -= nx * pull * 1.7;
        forces[target.id].y -= ny * pull * 1.7;
      } else {
        forces[source.id].x += nx * pull * 1.7;
        forces[source.id].y += ny * pull * 1.7;
      }
    });

    nodes.forEach((node) => {
      if (immovableIds.has(node.id)) {
        node.vx = 0;
        node.vy = 0;
        return;
      }
      const drag = Math.pow(0.88, dtScale);
      node.vx = clampNumber((Number(node.vx || 0) + forces[node.id].x * dtScale) * drag, -44, 44);
      node.vy = clampNumber((Number(node.vy || 0) + forces[node.id].y * dtScale) * drag, -44, 44);
      node.x = clampNumber(node.x + node.vx * dtScale, node.width / 2 + 36, sceneState.width - node.width / 2 - 36);
      node.y = clampNumber(node.y + node.vy * dtScale, node.height / 2 + 32, sceneState.height - node.height / 2 - 32);
      maxSpeed = Math.max(maxSpeed, Math.abs(node.vx), Math.abs(node.vy));
      if (Math.abs(node.vx) > 0.04 || Math.abs(node.vy) > 0.04) moved = true;
    });

    resolveModelGraphCollisions(nodes, sceneState.width, sceneState.height, draggedNodeId ? 3 : 4, immovableIds);
    sceneState.edges = refreshModelGraphEdgeGeometry(sceneState.edges, sceneState.nodeById);
    return {
      active: Boolean(draggedNodeId) || maxSpeed > 0.08,
      moved
    };
  }

  function bindModelGraphInteractions(root, sceneState) {
    const stage = root.querySelector(".model-graph-stage");
    if (!stage || !sceneState) return;
    destroyActiveModelGraphRuntime();
    hydrateModelGraphSceneElements(root, sceneState);
    const viewport = state.modelObservation.graphViewport && state.modelObservation.graphViewport.initialized
      ? constrainModelGraphViewport(stage, sceneState, state.modelObservation.graphViewport)
      : computeModelGraphViewportFit(stage, sceneState);
    state.modelObservation.graphViewport = viewport;
    applyModelGraphViewport(root, viewport);
    sceneState.selectedId = String(sceneState.selectedId || state.modelObservation.selectedGraphNodeId || "");
    const abortController = new AbortController();
    const signal = abortController.signal;
    let dragState = null;
    let disposed = false;
    let rafId = 0;
    let lastTick = typeof performance !== "undefined" ? performance.now() : Date.now();
    let settleFrames = 0;
    let lastPersistAt = 0;

    function commitViewport(nextViewport) {
      const applied = constrainModelGraphViewport(stage, sceneState, nextViewport);
      state.modelObservation.graphViewport = applied;
      applyModelGraphViewport(root, applied);
    }

    function releaseDragState() {
      dragState = null;
      stage.classList.remove("is-panning");
      stage.classList.remove("is-dragging-node");
      Array.from(root.querySelectorAll(".model-graph-node.is-dragging")).forEach((node) => {
        node.classList.remove("is-dragging");
      });
    }

    function persistGraphPositions(force) {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      if (!force && now - lastPersistAt < 140) return;
      lastPersistAt = now;
      storeModelGraphPositions(sceneState);
    }

    function refreshGraphScene(forcePersist) {
      updateModelGraphScene(root, sceneState);
      persistGraphPositions(Boolean(forcePersist));
    }

    function queueFrame() {
      if (disposed || rafId) return;
      rafId = requestAnimationFrame((timestamp) => {
        rafId = 0;
        if (disposed) return;
        const draggedNodeId = dragState && dragState.kind === "node" ? dragState.nodeId : "";
        const result = stepModelGraphPhysics(sceneState, {
          dtMs: timestamp - lastTick,
          draggedNodeId,
          selectedId: state.modelObservation.selectedGraphNodeId || sceneState.selectedId || ""
        });
        lastTick = timestamp;
        refreshGraphScene(false);
        if (dragState || result.active) {
          settleFrames = 0;
          queueFrame();
          return;
        }
        if (settleFrames < 2) {
          settleFrames += 1;
          queueFrame();
          return;
        }
        persistGraphPositions(true);
      });
    }

    function recordDragSample(activeDragState, point) {
      if (!activeDragState) return;
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      const samples = Array.isArray(activeDragState.samples) ? activeDragState.samples : [];
      samples.push({
        t: now,
        x: Number(point.x || 0),
        y: Number(point.y || 0)
      });
      while (samples.length > 6 || (samples.length > 2 && now - samples[0].t > 140)) {
        samples.shift();
      }
      activeDragState.samples = samples;
    }

    function dragVelocity(activeDragState) {
      const samples = Array.isArray(activeDragState && activeDragState.samples) ? activeDragState.samples : [];
      if (samples.length < 2) return { x: 0, y: 0 };
      const first = samples[0];
      const last = samples[samples.length - 1];
      const elapsed = Math.max(1, Number(last.t || 0) - Number(first.t || 0));
      return {
        x: clampNumber(((last.x - first.x) / elapsed) * 16, -34, 34),
        y: clampNumber(((last.y - first.y) / elapsed) * 16, -34, 34)
      };
    }

    stage.addEventListener("wheel", (event) => {
      event.preventDefault();
      const current = normalizeModelGraphViewport(state.modelObservation.graphViewport);
      const nextScale = clampNumber(current.scale * (event.deltaY < 0 ? 1.12 : 0.88), 0.42, 2.8);
      const rect = stage.getBoundingClientRect();
      const scenePoint = modelGraphClientToScene(stage, current, event.clientX, event.clientY);
      commitViewport({
        x: event.clientX - rect.left - scenePoint.x * nextScale,
        y: event.clientY - rect.top - scenePoint.y * nextScale,
        scale: nextScale,
        initialized: true
      });
    }, { passive: false, signal });

    stage.addEventListener("dblclick", (event) => {
      if (event.target.closest("[data-model-graph-node]")) return;
      commitViewport(computeModelGraphViewportFit(stage, sceneState));
    }, { signal });

    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const nodeTarget = event.target.closest("[data-model-graph-node]");
      hidePreview();
      if (nodeTarget) {
        const nodeId = String(nodeTarget.getAttribute("data-model-graph-node") || "");
        const node = sceneState.nodeById[nodeId];
        if (!node) return;
        const currentViewport = normalizeModelGraphViewport(state.modelObservation.graphViewport);
        const point = modelGraphClientToScene(stage, currentViewport, event.clientX, event.clientY);
        dragState = {
          kind: "node",
          pointerId: event.pointerId,
          nodeId,
          startClientX: event.clientX,
          startClientY: event.clientY,
          offsetX: point.x - node.x,
          offsetY: point.y - node.y,
          wasLocked: Boolean(node.locked),
          moved: false,
          samples: [],
          releaseVelocity: { x: 0, y: 0 },
          lastSceneX: node.x,
          lastSceneY: node.y,
          lastSceneT: typeof performance !== "undefined" ? performance.now() : Date.now()
        };
        recordDragSample(dragState, point);
        nodeTarget.dataset.dragSuppressClick = "0";
        try {
          stage.setPointerCapture(event.pointerId);
        } catch (_err) {
          // no-op
        }
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      dragState = {
        kind: "pan",
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originX: normalizeModelGraphViewport(state.modelObservation.graphViewport).x,
        originY: normalizeModelGraphViewport(state.modelObservation.graphViewport).y
      };
      stage.classList.add("is-panning");
      try {
        stage.setPointerCapture(event.pointerId);
      } catch (_err) {
        // no-op
      }
      event.preventDefault();
    }, { signal });

    stage.addEventListener("pointermove", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      if (dragState.kind === "pan") {
        const current = normalizeModelGraphViewport(state.modelObservation.graphViewport);
        commitViewport({
          x: dragState.originX + (event.clientX - dragState.startClientX),
          y: dragState.originY + (event.clientY - dragState.startClientY),
          scale: current.scale,
          initialized: true
        });
        return;
      }
      if (dragState.kind !== "node") return;
      const node = sceneState.nodeById[dragState.nodeId];
      const btn = sceneState.nodeElements ? sceneState.nodeElements[dragState.nodeId] : null;
      if (!node || !btn) return;
      const travel = Math.hypot(event.clientX - dragState.startClientX, event.clientY - dragState.startClientY);
      if (!dragState.moved && travel <= 4) return;
      if (!dragState.moved) {
        dragState.moved = true;
        btn.dataset.dragSuppressClick = "1";
        btn.classList.add("is-dragging");
        stage.classList.add("is-dragging-node");
        node.vx = 0;
        node.vy = 0;
      }
      const currentViewport = normalizeModelGraphViewport(state.modelObservation.graphViewport);
      const point = modelGraphClientToScene(stage, currentViewport, event.clientX, event.clientY);
      node.x = clampNumber(point.x - dragState.offsetX, node.width / 2 + 36, sceneState.width - node.width / 2 - 36);
      node.y = clampNumber(point.y - dragState.offsetY, node.height / 2 + 32, sceneState.height - node.height / 2 - 32);
      node.anchorX = node.x;
      node.anchorY = node.y;
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      const elapsed = Math.max(1, now - Number(dragState.lastSceneT || now));
      dragState.releaseVelocity = {
        x: clampNumber(((node.x - Number(dragState.lastSceneX || node.x)) / elapsed) * 16, -38, 38),
        y: clampNumber(((node.y - Number(dragState.lastSceneY || node.y)) / elapsed) * 16, -38, 38)
      };
      dragState.lastSceneX = node.x;
      dragState.lastSceneY = node.y;
      dragState.lastSceneT = now;
      recordDragSample(dragState, { x: node.x, y: node.y });
      stepModelGraphPhysics(sceneState, {
        dtMs: 16,
        draggedNodeId: dragState.nodeId,
        selectedId: state.modelObservation.selectedGraphNodeId || sceneState.selectedId || ""
      });
      refreshGraphScene(false);
      queueFrame();
    }, { signal });

    stage.addEventListener("pointerup", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      try {
        stage.releasePointerCapture(event.pointerId);
      } catch (_err) {
        // no-op
      }
      if (dragState.kind === "node") {
        const node = sceneState.nodeById[dragState.nodeId];
        const btn = sceneState.nodeElements ? sceneState.nodeElements[dragState.nodeId] : null;
        if (node && btn) {
          if (dragState.moved) {
            if (dragState.wasLocked) {
              node.locked = true;
              state.modelObservation.graphPinnedNodeIds[dragState.nodeId] = true;
              node.vx = 0;
              node.vy = 0;
              btn.classList.add("is-pinned");
            } else {
              node.locked = false;
              delete state.modelObservation.graphPinnedNodeIds[dragState.nodeId];
              const velocity = dragVelocity(dragState);
              const fallbackVelocity = dragState.releaseVelocity || { x: 0, y: 0 };
              const baseVelocityX = Math.abs(velocity.x) + Math.abs(velocity.y) > 0.2 ? velocity.x : Number(fallbackVelocity.x || 0);
              const baseVelocityY = Math.abs(velocity.x) + Math.abs(velocity.y) > 0.2 ? velocity.y : Number(fallbackVelocity.y || 0);
              node.vx = clampNumber(baseVelocityX * 7, -56, 56);
              node.vy = clampNumber(baseVelocityY * 7, -56, 56);
              btn.classList.remove("is-pinned");
            }
            node.anchorX = node.x;
            node.anchorY = node.y;
            refreshGraphScene(true);
            queueFrame();
          } else {
            node.locked = dragState.wasLocked;
          }
        }
      }
      releaseDragState();
    }, { signal });

    stage.addEventListener("pointercancel", (event) => {
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      if (dragState.kind === "node") {
        const node = sceneState.nodeById[dragState.nodeId];
        if (node) node.locked = dragState.wasLocked;
      }
      releaseDragState();
    }, { signal });

    Object.keys(sceneState.nodeElements || {}).forEach((nodeId) => {
      const btn = sceneState.nodeElements[nodeId];
      const node = sceneState.nodeById[nodeId];
      if (!btn || !node) return;
      btn.classList.toggle("is-pinned", Boolean(node.locked));
      btn.addEventListener("dblclick", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const pendingClick = Number(btn.dataset.clickTimer || 0);
        if (pendingClick) {
          window.clearTimeout(pendingClick);
          btn.dataset.clickTimer = "0";
        }
        btn.dataset.pinSuppressClick = "1";
        const nextPinned = !Boolean(state.modelObservation.graphPinnedNodeIds[nodeId]);
        if (nextPinned) {
          state.modelObservation.graphPinnedNodeIds[nodeId] = true;
        } else {
          delete state.modelObservation.graphPinnedNodeIds[nodeId];
        }
        node.locked = nextPinned;
        node.anchorX = node.x;
        node.anchorY = node.y;
        node.vx = 0;
        node.vy = 0;
        btn.classList.toggle("is-pinned", nextPinned);
        refreshGraphScene(true);
      }, { signal });
    });

    activeModelGraphRuntime = {
      destroy() {
        disposed = true;
        if (rafId) {
          cancelAnimationFrame(rafId);
          rafId = 0;
        }
        abortController.abort();
        releaseDragState();
      }
    };
  }

  function renderModelObservationCanvas() {
    const root = document.getElementById("model-observation-canvas");
    if (!root) return;
    destroyActiveModelGraphRuntime();
    const observation = state.modelObservation.observation || {};
    const focus = String(state.modelObservation.graphFocus || "all").trim().toLowerCase() || "all";
    const search = String(state.modelObservation.graphSearch || "");
    const viewport = normalizeModelGraphViewport(state.modelObservation.graphViewport);
    const active = document.activeElement;
    const restoreSearchFocus = Boolean(active && active.id === "model-graph-search");
    const restoreSearchPosition =
      restoreSearchFocus && typeof active.selectionStart === "number" ? active.selectionStart : null;
    const graph = buildModelObservationGraph(observation);
    const chips = [
      { value: "all", label: "All" },
      { value: "archetype", label: "Archetypes" },
      { value: "win", label: "Win Conditions" },
      { value: "shell", label: "Shells" },
      { value: "synergy", label: "Synergy" },
      { value: "card", label: "Cards" }
    ];

    if (!graph.nodes.length) {
      root.innerHTML =
        `<div class="model-graph-shell">` +
        `<div class="deck-card-empty">No learned features are available in the current production artifact.</div>` +
        `</div>`;
      return;
    }

    const view = filterModelObservationGraph(graph, {
      focus,
      search,
      selectedId: state.modelObservation.selectedGraphNodeId
    });
    state.modelObservation.selectedGraphNodeId = view.selectedId || "";

    const toolbar =
      `<div class="model-graph-toolbar">` +
      `<div class="model-graph-filter-row">` +
      chips
        .map((chip) => {
          const isActive = focus === chip.value;
          const count = graph.counts[chip.value] || graph.counts.all || 0;
          return (
            `<button type="button" class="model-graph-filter-chip ${isActive ? "is-active" : ""}" data-model-graph-focus="${escAttr(chip.value)}" aria-pressed="${isActive ? "true" : "false"}">` +
            `<span>${esc(chip.label)}</span>` +
            `<strong>${esc(count)}</strong>` +
            `</button>`
          );
        })
        .join("") +
      `</div>` +
      `<div class="model-graph-tools">` +
      `<label class="model-graph-search">` +
      `<span>Search</span>` +
      `<input id="model-graph-search" type="search" placeholder="Card, shell, archetype..." value="${escAttr(search)}" />` +
      `</label>` +
      `<div class="model-graph-zoom-tools">` +
      `<button type="button" class="card-action-btn secondary" data-model-graph-zoom="out" aria-label="Zoom out">-</button>` +
      `<button type="button" class="card-action-btn secondary" data-model-graph-zoom="fit">Fit</button>` +
      `<button type="button" class="card-action-btn secondary" data-model-graph-zoom="in" aria-label="Zoom in">+</button>` +
      `<span class="model-graph-zoom-label" data-model-graph-zoom-label>${esc(`${Math.round(viewport.scale * 100)}%`)}</span>` +
      `</div>` +
      `<button type="button" class="card-action-btn secondary" data-model-graph-reset="1">Reset View</button>` +
      `</div>` +
      `</div>` +
      `<div class="model-graph-caption">` +
      `<span>${esc(view.nodes.length)} nodes • ${esc(view.edges.length)} links</span>` +
      `<span>${esc(view.matchedCount ? `${view.matchedCount} search matches` : "Wheel to zoom • drag background to pan • drag or fling nodes • double-click to pin")}</span>` +
      `</div>`;
    let sceneState = null;

    if (!view.nodes.length) {
      root.innerHTML =
        `<div class="model-graph-shell">` +
        toolbar +
        `<div class="deck-card-empty">No nodes match the current filter. Clear the search or widen the focus.</div>` +
        `</div>`;
    } else {
      const laidOut = layoutModelObservationGraph(view.nodes, view.edges, view.selectedId, {
        positions: state.modelObservation.graphNodePositions,
        pinnedIds: state.modelObservation.graphPinnedNodeIds
      });
      sceneState = laidOut;
      const nodeMarkup = laidOut.nodes
        .map((node) => {
          const image = node.imageUrl || node.imageFallback || cardBackFor(node.label);
          const previewTitle = node.type === "card" ? node.label : (node.featureCards[0] || node.label);
          const previewImage = node.imageUrl || node.imageFallback || cardBackFor(previewTitle);
          const style =
            `left:${(node.x - node.width / 2).toFixed(1)}px;` +
            `top:${(node.y - node.height / 2).toFixed(1)}px;` +
            `width:${node.width.toFixed(1)}px;` +
            `height:${node.height.toFixed(1)}px;`;
          if (node.type === "card") {
            return (
              `<button type="button" class="model-graph-node is-card ${node.locked ? "is-pinned" : ""} ${node.isSelected ? "is-selected" : ""} ${node.isDimmed ? "is-dimmed" : ""}" style="${style}" data-model-graph-node="${escAttr(node.id)}" data-preview-title="${escAttr(previewTitle)}" data-preview-image="${escAttr(previewImage)}">` +
              `<img class="model-graph-card-thumb ${node.imageUrl ? "" : "is-fallback"}" src="${escAttr(image)}" alt="${escAttr(node.label)} artwork" data-fallback-src="${escAttr(node.imageFallback || cardBackFor(node.label))}" />` +
              `<span class="model-graph-card-shade"></span>` +
              `<span class="model-graph-card-title">${esc(truncateText(node.label, 22))}</span>` +
              `</button>`
            );
          }
          return (
            `<button type="button" class="model-graph-node is-feature is-${escAttr(node.type)} ${node.locked ? "is-pinned" : ""} ${node.isSelected ? "is-selected" : ""} ${node.isDimmed ? "is-dimmed" : ""}" style="${style}" data-model-graph-node="${escAttr(node.id)}" data-preview-title="${escAttr(previewTitle)}" data-preview-image="${escAttr(previewImage)}">` +
            `<span class="model-graph-node-aura"></span>` +
            `<span class="model-graph-node-avatar">` +
            `<img class="${node.imageUrl ? "" : "is-fallback"}" src="${escAttr(image)}" alt="${escAttr(node.label)} artwork" data-fallback-src="${escAttr(node.imageFallback || cardBackFor(node.label))}" />` +
            `</span>` +
            `<span class="model-graph-node-kicker">${esc(modelGraphTypeLabel(node.type))}</span>` +
            `<strong class="model-graph-node-title">${esc(truncateText(node.label, node.type === "archetype" ? 34 : 26))}</strong>` +
            `<span class="model-graph-node-subtitle">${esc(truncateText(node.subtitle || node.metaLine || node.description || "", node.type === "archetype" ? 44 : 34))}</span>` +
            `</button>`
          );
        })
        .join("");
      const edgeMarkup = laidOut.edges
        .map(
          (edge) =>
            `<line class="model-graph-edge is-${escAttr(edge.kind)} ${edge.isDimmed ? "is-dimmed" : ""}" data-model-graph-edge="${escAttr(edge.id)}" x1="${edge.x1.toFixed(1)}" y1="${edge.y1.toFixed(1)}" x2="${edge.x2.toFixed(1)}" y2="${edge.y2.toFixed(1)}" stroke-width="${clampNumber(0.9 + Number(edge.weight || 0) * 0.36, 1, 3.4).toFixed(2)}" />`
        )
        .join("");
      root.innerHTML =
        `<div class="model-graph-shell">` +
        toolbar +
        `<div class="model-graph-main">` +
        `<section class="model-graph-stage">` +
        `<div class="model-graph-stage-glow"></div>` +
        `<div class="model-graph-scene" style="width:${laidOut.width}px; height:${laidOut.height}px;">` +
        `<svg class="model-graph-links" viewBox="0 0 ${laidOut.width} ${laidOut.height}" role="presentation" aria-hidden="true">${edgeMarkup}</svg>` +
        `<div class="model-graph-nodes">${nodeMarkup}</div>` +
        `</div>` +
        `</section>` +
        `<aside class="model-graph-inspector">${renderModelObservationGraphInspector({
          selectedNode: view.selectedNode,
          nodeById: graph.nodesById,
          visibleIds: view.visibleIds
        })}</aside>` +
        `</div>` +
        `</div>`;
    }

    bindCardImageFallbacks(root);
    bindPreviewInteractions(root);
    if (sceneState) {
      bindModelGraphInteractions(root, sceneState);
      applyModelGraphViewport(root, normalizeModelGraphViewport(state.modelObservation.graphViewport));
    }
    Array.from(root.querySelectorAll("[data-model-graph-focus]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modelObservation.graphFocus = String(btn.getAttribute("data-model-graph-focus") || "all");
        renderModelObservationCanvas();
      });
    });
    const searchInput = root.querySelector("#model-graph-search");
    if (searchInput) {
      searchInput.addEventListener("input", debounce(() => {
        state.modelObservation.graphSearch = String(searchInput.value || "");
        renderModelObservationCanvas();
      }, 260));
      searchInput.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (!searchInput.value) return;
        state.modelObservation.graphSearch = "";
        renderModelObservationCanvas();
      });
      if (restoreSearchFocus) {
        searchInput.focus();
        if (restoreSearchPosition != null) {
          searchInput.setSelectionRange(restoreSearchPosition, restoreSearchPosition);
        }
      }
    }
    Array.from(root.querySelectorAll("[data-model-graph-reset]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modelObservation.graphFocus = "all";
        state.modelObservation.graphSearch = "";
        state.modelObservation.selectedGraphNodeId = "";
        state.modelObservation.graphNodePositions = {};
        state.modelObservation.graphPinnedNodeIds = {};
        state.modelObservation.graphViewport = {
          x: 0,
          y: 0,
          scale: 1,
          initialized: false
        };
        renderModelObservationCanvas();
      });
    });
    Array.from(root.querySelectorAll("[data-model-graph-zoom]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!sceneState) return;
        const stage = root.querySelector(".model-graph-stage");
        if (!stage) return;
        const mode = String(btn.getAttribute("data-model-graph-zoom") || "").trim().toLowerCase();
        if (mode === "fit") {
          state.modelObservation.graphViewport = computeModelGraphViewportFit(stage, sceneState);
          applyModelGraphViewport(root, normalizeModelGraphViewport(state.modelObservation.graphViewport));
          return;
        }
        const current = normalizeModelGraphViewport(state.modelObservation.graphViewport);
        const nextScale = clampNumber(current.scale * (mode === "in" ? 1.18 : 0.84), 0.42, 2.8);
        const rect = stage.getBoundingClientRect();
        const anchorX = rect.left + rect.width / 2;
        const anchorY = rect.top + rect.height / 2;
        const scenePoint = modelGraphClientToScene(stage, current, anchorX, anchorY);
        state.modelObservation.graphViewport = constrainModelGraphViewport(stage, sceneState, {
          x: rect.width / 2 - scenePoint.x * nextScale,
          y: rect.height / 2 - scenePoint.y * nextScale,
          scale: nextScale,
          initialized: true
        });
        applyModelGraphViewport(root, normalizeModelGraphViewport(state.modelObservation.graphViewport));
      });
    });
    Array.from(root.querySelectorAll("[data-model-graph-node]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.dragSuppressClick === "1") {
          btn.dataset.dragSuppressClick = "0";
          return;
        }
        if (btn.dataset.pinSuppressClick === "1") {
          btn.dataset.pinSuppressClick = "0";
          return;
        }
        const pendingClick = Number(btn.dataset.clickTimer || 0);
        if (pendingClick) window.clearTimeout(pendingClick);
        const nodeId = String(btn.getAttribute("data-model-graph-node") || "");
        btn.dataset.clickTimer = String(
          window.setTimeout(() => {
            btn.dataset.clickTimer = "0";
            if (!btn.isConnected) return;
            state.modelObservation.selectedGraphNodeId = nodeId;
            renderModelObservationCanvas();
          }, 180)
        );
      });
    });
    Array.from(root.querySelectorAll("[data-model-graph-card]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const title = String(btn.getAttribute("data-model-graph-card") || "");
        const targetNode = String(btn.getAttribute("data-model-graph-target") || "");
        if (targetNode) {
          state.modelObservation.selectedGraphNodeId = targetNode;
          renderModelObservationCanvas();
          return;
        }
        if (title) openMainCardModal(title);
      });
    });
    Array.from(root.querySelectorAll("[data-model-card-open]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const title = String(btn.getAttribute("data-model-card-open") || "");
        if (title) openMainCardModal(title);
      });
    });
  }

  function renderModelObservationTraining() {
    const bar = document.getElementById("model-training-progress-bar");
    const line = document.getElementById("model-training-status-line");
    const runBtn = document.getElementById("model-training-run-btn");
    const live = document.getElementById("model-training-live");
    const training = state.modelObservation.training || {};
    const isRunning = Boolean(training.isRunning);
    const progressPct = Math.max(0, Math.min(100, Number(training.progressPct || 0)));
    const step = Number(training.step || 0);
    const totalSteps = Number(training.totalSteps || 0);
    const stage = String(training.stage || "").trim() || "idle";
    const updatedAt = training.updatedAt ? new Date(training.updatedAt).toLocaleTimeString() : "";
    const events = Array.isArray(training.events) ? training.events : [];
    if (bar) {
      bar.style.width = `${progressPct}%`;
      bar.classList.toggle("is-active", isRunning);
    }
    if (runBtn) {
      runBtn.disabled = isRunning;
      runBtn.textContent = isRunning ? "Training..." : "Train Model";
    }
    if (line) {
      if (isRunning) {
        line.textContent = `${training.message || "Training"} (${step}/${totalSteps}, ${progressPct.toFixed(1)}%)`;
      } else if (training.status === "completed") {
        line.textContent = `Training completed. Saved model ${training.modelId || ""}.`;
      } else if (training.status === "failed") {
        line.textContent = training.error || "Training failed.";
      } else {
        line.textContent = "No active training job.";
      }
    }
    if (live) {
      if (!isRunning && training.status !== "completed" && training.status !== "failed") {
        live.innerHTML = '<div class="deck-card-empty">No active training job.</div>';
      } else {
      const stageLabel = stage
        .split("-")
        .map((part) => part ? part[0].toUpperCase() + part.slice(1) : "")
        .join(" ");
      const eventRows = events.length
        ? events
            .slice()
            .reverse()
            .slice(0, 8)
            .map((event) => {
              const stamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "";
              const eventStage = String(event.stage || "").trim() || "idle";
              return (
                `<div class="model-training-event">` +
                `<span class="model-training-event-stage">${esc(eventStage)}</span>` +
                `<div class="model-training-event-body">` +
                `<strong>${esc(event.message || "Progress update")}</strong>` +
                `<small>${esc(stamp)} | ${esc((event.step || 0) + "/" + (event.totalSteps || 0))} | ${esc(Number(event.progressPct || 0).toFixed(1))}%</small>` +
                `</div>` +
                `</div>`
              );
            })
            .join("")
        : '<div class="deck-card-empty">No training events yet.</div>';
      live.innerHTML =
        `<div class="model-training-overview ${isRunning ? "is-running" : ""}">` +
        `<div class="model-training-chip-row">` +
        `<span class="model-training-chip">${esc(String(training.status || "idle").toUpperCase())}</span>` +
        `<span class="model-training-chip">${esc(stageLabel || "Idle")}</span>` +
        `<span class="model-training-chip">${esc(step + "/" + totalSteps)}</span>` +
        `<span class="model-training-chip">${esc(progressPct.toFixed(1) + "%")}</span>` +
        `</div>` +
        `<div class="model-training-meta">` +
        `<span>Job ${esc(training.jobId || "-")}</span>` +
        `<span>${esc(updatedAt || "No updates yet")}</span>` +
        `</div>` +
        `</div>` +
        `<div class="model-training-events">${eventRows}</div>`;
      }
    }
    writeModelObservationForm();
  }

  function renderModelObservationDetail() {
    const root = document.getElementById("model-observation-detail");
    if (!root) return;
    const row = modelObservationSelectedModel();
    if (!row) {
      root.innerHTML = '<div class="deck-card-empty">Select a saved model to inspect version details.</div>';
      return;
    }
    const metrics = row.trainingMetrics && typeof row.trainingMetrics === "object" ? row.trainingMetrics : {};
    const metricRows = Object.keys(metrics)
      .filter((key) => typeof metrics[key] === "number")
      .slice(0, 8)
      .map((key) => `<div class="model-detail-row"><span>${esc(key)}</span><strong>${esc(Number(metrics[key]).toFixed(4))}</strong></div>`)
      .join("") || '<div class="model-detail-row"><span>Metrics</span><strong>n/a</strong></div>';
    const sourceCounts = row.sourceCounts && typeof row.sourceCounts === "object" ? row.sourceCounts : {};
    const sourceRows = Object.keys(sourceCounts)
      .sort((a, b) => String(a).localeCompare(String(b)))
      .map((key) => `<div class="model-detail-row"><span>${esc(key)}</span><strong>${esc(sourceCounts[key])}</strong></div>`)
      .join("") || '<div class="model-detail-row"><span>Sources</span><strong>0</strong></div>';
    const badgeKind = `<span class="model-detail-badge">${esc(row.kind || "trained")}</span>`;
    const badgeStatus = `<span class="model-detail-badge">${esc(row.status || "ready")}</span>`;
    const badgeLive = row.isProduction ? `<span class="model-detail-badge is-live">Live</span>` : "";
    root.innerHTML =
      `<div class="model-detail-hero">` +
      `<div class="model-detail-title">${esc(row.label || row.id || "Saved Model")}</div>` +
      `<div class="model-detail-badge-row">${badgeKind}${badgeStatus}${badgeLive}</div>` +
      `</div>` +
      `<div class="model-detail-section"><h4>Counts</h4>` +
      `<div class="model-detail-row"><span>Training Decks</span><strong>${esc(row.trainingDeckCount || 0)}</strong></div>` +
      `<div class="model-detail-row"><span>Win Conditions</span><strong>${esc(row.winConditionCount || 0)}</strong></div>` +
      `<div class="model-detail-row"><span>Synergy Clusters</span><strong>${esc(row.synergyClusterCount || 0)}</strong></div>` +
      `<div class="model-detail-row"><span>Device</span><strong>${esc(row.torchDevice || "-")}</strong></div>` +
      `<div class="model-detail-row"><span>Epochs</span><strong>${esc(row.epochs || 0)}</strong></div>` +
      `</div>` +
      `<div class="model-detail-section"><h4>Source Mix</h4>${sourceRows}</div>` +
      `<div class="model-detail-section"><h4>Top Metrics</h4>${metricRows}</div>`;
  }

  function renderModelObservation() {
    renderModelObservationStatus();
    renderModelObservationModels();
    renderModelObservationCanvas();
    renderModelObservationTraining();
    renderModelObservationDetail();
  }

  function stopModelObservationTrainingPoll() {
    if (state.modelObservation.pollTimer) {
      window.clearInterval(state.modelObservation.pollTimer);
      state.modelObservation.pollTimer = 0;
    }
  }

  function ensureModelObservationTrainingPoll() {
    if (state.modelObservation.pollTimer) return;
    state.modelObservation.pollTimer = window.setInterval(async () => {
      try {
        await loadModelObservationTrainingStatus();
      } catch (_err) {
        // keep the current UI state if polling fails
      }
    }, 1500);
  }

  async function loadModelObservationOverview() {
    state.modelObservation.loading = true;
    try {
      const overview = await api("/api/model-observation/overview");
      state.modelObservation.overview = overview;
      state.modelObservation.training = overview.training || state.modelObservation.training;
      state.modelObservation.models = Array.isArray(overview.models) ? overview.models : [];
      state.modelObservation.observation = overview.observation || {};
      hydrateModelObservationForm(overview.defaults || {});
      if (!state.modelObservation.selectedModelId) {
        const production = state.modelObservation.models.find((row) => row.isProduction);
        state.modelObservation.selectedModelId = String((production && production.id) || ((state.modelObservation.models[0] || {}).id || ""));
      }
      if (overview.status) {
        state.autoBuilder.status = overview.status;
      }
      if (state.modelObservation.training && state.modelObservation.training.isRunning) ensureModelObservationTrainingPoll();
      else stopModelObservationTrainingPoll();
      renderModelObservation();
      renderAutoBuilderStatus();
    } finally {
      state.modelObservation.loading = false;
    }
  }

  async function loadModelObservationTrainingStatus() {
    const training = await api("/api/model-observation/training");
    state.modelObservation.training = training;
    renderModelObservationTraining();
    if (training.isRunning) {
      ensureModelObservationTrainingPoll();
      return;
    }
    stopModelObservationTrainingPoll();
    if (training.status === "completed" || training.status === "failed") {
      await loadModelObservationOverview();
    }
  }

  async function startModelObservationTraining() {
    const form = readModelObservationForm();
    state.modelObservation.training = {
      isRunning: true,
      jobId: "",
      label: form.label,
      status: "starting",
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      finishedAt: null,
      stage: "submitting",
      step: 0,
      totalSteps: 11,
      progressPct: 1.0,
      message: "Submitting training job...",
      error: "",
      outputDir: "",
      modelId: "",
      params: form,
      result: {},
      events: [
        {
          timestamp: new Date().toISOString(),
          status: "starting",
          stage: "submitting",
          step: 0,
          totalSteps: 11,
          progressPct: 1.0,
          message: "Submitting training job..."
        }
      ]
    };
    renderModelObservationTraining();
    const training = await api("/api/model-observation/training", {
      method: "POST",
      body: {
        label: form.label,
        epochs: form.epochs,
      }
    });
    state.modelObservation.training = training;
    renderModelObservationTraining();
    ensureModelObservationTrainingPoll();
    window.setTimeout(() => {
      void loadModelObservationTrainingStatus().catch(() => {});
    }, 150);
    return training;
  }

  async function snapshotModelObservationProduction() {
    const { confirmed, value } = await confirmModal({
      title: "Snapshot Production Model",
      body: "Save the current production model to the Vault with a label.",
      requireInput: true,
      inputPlaceholder: "Snapshot label",
      inputDefault: "Production Snapshot",
      confirmLabel: "Save Snapshot"
    });
    if (!confirmed) return null;
    const row = await api("/api/model-observation/models/snapshot", {
      method: "POST",
      body: { label: String(value || "").trim() }
    });
    await loadModelObservationOverview();
    state.modelObservation.selectedModelId = String((row && row.id) || "");
    renderModelObservation();
    return row;
  }

  async function promoteModelObservationModel(modelId) {
    const row = await api(`/api/model-observation/models/${encodeURIComponent(modelId)}/promote`, {
      method: "POST"
    });
    state.modelObservation.selectedModelId = String((row && row.id) || modelId || "");
    await Promise.all([loadModelObservationOverview(), loadAutoBuilderStatus()]);
    renderModelObservation();
    renderAutoBuilder();
    return row;
  }

  async function importCollectionCsv() {
    const fileInput = document.getElementById("collection-csv-file");
    if (!fileInput || !fileInput.files || !fileInput.files.length) {
      throw new Error("Choose a CSV or JSON file first.");
    }
    const modeSelect = document.getElementById("collection-import-mode");
    const importMode = String((modeSelect && modeSelect.value) || "merge").trim().toLowerCase();
    const replaceExisting = importMode === "replace";
    if (replaceExisting) {
      const { confirmed } = await confirmModal({
        title: "Replace Collection",
        body: "Replace mode will overwrite your current collection. Continue?",
        confirmLabel: "Replace"
      });
      if (!confirmed) return;
    }
    const file = fileInput.files[0];
    const raw = await file.text();
    const lowerName = String(file && file.name ? file.name : "").toLowerCase();
    const isJson = lowerName.endsWith(".json") || String(file.type || "").includes("json");
    const endpoint = isJson ? "/api/collection/import-json" : "/api/collection/import-csv";
    const body = isJson ? { jsonText: raw, replaceExisting } : { csvText: raw, replaceExisting };
    const payload = await api(endpoint, {
      method: "POST",
      body
    });
    renderCollection(payload);
    return payload;
  }

  async function exportCollection(formatName) {
    const format = String(formatName || "json").trim().toLowerCase();
    if (format === "json") {
      const payload = await api("/api/collection/export?format=json");
      downloadJson(`riftbound-collection-${new Date().toISOString().slice(0, 10)}.json`, payload);
      return;
    }
    if (format !== "csv") {
      throw new Error("Unsupported export format.");
    }
    const headers = {};
    const token = currentAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch("/api/collection/export?format=csv", {
      headers: Object.keys(headers).length ? headers : undefined
    });
    if (!res.ok) throw new Error("Could not export collection CSV.");
    const text = await res.text();
    const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `riftbound-collection-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function resetCollection() {
    const { confirmed, value } = await confirmModal({
      title: "Reset Collection",
      body: "This will permanently clear all your collection data. A JSON backup will be downloaded automatically. Type RESET to confirm.",
      requireInput: true,
      inputPlaceholder: "Type RESET to confirm",
      inputMatch: "RESET",
      confirmLabel: "Reset Collection"
    });
    if (!confirmed) return;
    await exportCollection("json");
    const payload = await api("/api/collection/reset", {
      method: "POST",
      body: { confirmPhrase: value, createBackup: false }
    });
    renderCollection(payload.snapshot || {});
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

  async function writeDeckToForm(deck, options) {
    const opts = options || {};
    applyEditorMeta({
      deckId: opts.deckId,
      bucket: opts.libraryBucket,
      visibility: opts.visibility,
      publishedAt: opts.publishedAt,
      ownerDisplayName: opts.ownerDisplayName
    });
    state.deck = normalizeDeckPayload(deck);
    sanitizeMainDeckLegendCards();
    await refreshEligibility(state.deck.legendTitle, { applyRecommended: false, inferChampion: true, validate: false });
    state.editor.lastSavedFingerprint = opts.markSaved ? currentDeckFingerprint() : "";
    setWorkspaceTab("deck");
    renderDeckWorkbench();
    scheduleValidation(true);
    updateDeckSaveState();
  }

  async function clearDeckWorkbench() {
    const formatName = String(state.deck.format || "constructed").trim() || "constructed";
    state.analysis.active = false;
    state.analysis.summary = null;
    state.analysis.replacementByCard = {};
    state.analysis.mainMissingByTitle = {};
    state.analysis.mainOwnedCopies = 0;
    state.ui.replacementCardTitle = "";
    closeReplacementModal();
    await writeDeckToForm({
      name: "Untitled Deck",
      source: "builder",
      format: formatName,
      legendTitle: "",
      chosenChampionTitle: "",
      main: {},
      runes: {},
      battlefields: [],
      sideboard: {}
    }, { libraryBucket: "saved", visibility: "private", markSaved: true });
  }

  async function openLibraryDeck(deckId) {
    const id = String(deckId || "");
    if (!id) return;
    const row = state.library.find((entry) => String(entry.id) === id);
    if (!row || !row.deck) return;
    const deck = { ...row.deck, name: row.name || row.deck.name };
    await writeDeckToForm(deck, {
      deckId: row.id,
      libraryBucket: row.bucket,
      visibility: row.visibility,
      publishedAt: row.publishedAt,
      ownerDisplayName: row.ownerDisplayName,
      markSaved: true
    });
    setStatus(`Loaded "${row.name}".`, false);
  }

  async function setLibraryDeckBucket(deckId, bucket) {
    const id = String(deckId || "");
    const nextBucket = String(bucket || "").trim().toLowerCase() === "built" ? "built" : "saved";
    if (!id) return;

    // Optimistic update — flip the bucket in local state and re-render immediately.
    const prevLibrary = state.library.slice();
    const idx = state.library.findIndex((entry) => String((entry && entry.id) || "") === id);
    if (idx >= 0) {
      const rows = state.library.slice();
      rows[idx] = { ...rows[idx], bucket: nextBucket };
      state.library = rows;
    }
    sortLibraryRows();
    renderLibrary();
    refreshCollectionUsageFromLibraryState();
    setStatus(nextBucket === "built" ? "Deck moved to Built Decks." : "Deck moved to Saved Decks.", false);
    // Briefly highlight the moved tile to confirm the action.
    window.setTimeout(() => {
      const movedTile = document.querySelector(`[data-lib-id="${CSS.escape(id)}"]`);
      if (movedTile) {
        movedTile.classList.add("is-just-moved");
        window.setTimeout(() => movedTile.classList.remove("is-just-moved"), 600);
      }
    }, 0);

    // Background API call — roll back on failure.
    try {
      const updated = await api(`/api/decks/library/${encodeURIComponent(id)}/bucket`, {
        method: "PUT",
        body: { bucket: nextBucket }
      });
      const row = upsertLibraryRow(updated);
      if (row && String(state.editor.deckId || "").trim() === String(row.id || "").trim()) {
        markDeckSaved(row);
      } else {
        updateDeckSaveState();
      }
      scheduleMetaDeckRefresh();
    } catch (err) {
      state.library = prevLibrary;
      renderLibrary();
      refreshCollectionUsageFromLibraryState();
      setStatus(err.message || "Could not move deck.", true);
    }
  }

  let _deckSaveAbortCtrl = null;

  async function saveCurrentDeckToLibrary() {
    // Cancel any in-flight save to prevent race conditions
    if (_deckSaveAbortCtrl) _deckSaveAbortCtrl.abort();
    _deckSaveAbortCtrl = new AbortController();
    const signal = _deckSaveAbortCtrl.signal;
    const deck = currentDeckFromForm();
    const body = {
      name: deck.name,
      source: deck.source,
      bucket: normalizeLibraryBucket(state.editor.bucket),
      visibility: normalizeDeckVisibility(state.editor.visibility),
      deck
    };
    const deckId = String(state.editor.deckId || "").trim();
    const saved = await api(
      deckId ? `/api/decks/library/${encodeURIComponent(deckId)}` : "/api/decks/library",
      {
        method: deckId ? "PUT" : "POST",
        body,
        signal
      }
    );
    markDeckSaved(saved);
    await Promise.all([loadLibrary(), loadCollection(), refreshMetaSearchResults()]);
    return saved;
  }

  async function loadCoreWorkspace() {
    if (state.ui.loadedWorkspaces.core) return;
    await loadCardCatalog();
    await loadFormats();
    await refreshEligibility(state.deck.legendTitle, { applyRecommended: false, inferChampion: true, validate: false });
    await refreshAutoBuilderEligibility(state.autoBuilder.legendTitle, { render: false });
    renderDeckWorkbench();
    state.ui.loadedWorkspaces.core = true;
  }

  async function ensureWorkspaceLoaded(workspace) {
    await loadCoreWorkspace();

    // Library sidebar is always visible — load it once in the background
    if (!state.ui.loadedWorkspaces.library) {
      state.ui.loadedWorkspaces.library = true;
      void loadLibrary();
    }

    const tab = String(workspace || state.ui.workspaceTab || "deck").trim();
    if (tab === "wizard") {
      await loadCollection();
      state.ui.loadedWorkspaces.wizard = true;
      return;
    }
    if (tab === "collection") {
      await loadCollection();
      state.ui.loadedWorkspaces.collection = true;
      return;
    }
    if (tab === "discover") {
      await Promise.all([loadMetaDecks(), loadCommunityDecks()]);
      state.ui.loadedWorkspaces.discover = true;
      return;
    }
    if (tab === "auto-builder") {
      if (state.auth.featureFlags && state.auth.featureFlags.autoBuilderEnabled === false) return;
      try {
        await loadAutoBuilderStatus();
      } catch (_err) {
        renderAutoBuilderStatus();
      }
      state.ui.loadedWorkspaces.autoBuilder = true;
      return;
    }
    if (tab === "model-observation") {
      if (!state.auth.featureFlags || !state.auth.featureFlags.modelObservationEnabled) return;
      try {
        await loadModelObservationOverview();
      } catch (_err) {
        renderModelObservation();
      }
      state.ui.loadedWorkspaces.modelObservation = true;
      return;
    }
    await loadCollection();
    state.ui.loadedWorkspaces.deck = true;
  }

  async function loadInitialWorkspace() {
    await ensureWorkspaceLoaded(state.ui.workspaceTab);
    renderAutoBuilder();
    renderModelObservation();
    scheduleValidation(true);
    setStatus("Ready", false);
  }

  function bindEvents() {
    const authLoginForm = document.getElementById("auth-login-form");
    if (authLoginForm) {
      authLoginForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const emailEl = document.getElementById("auth-email");
        const passwordEl = document.getElementById("auth-password");
        const signinBtn = document.getElementById("auth-signin-btn");
        const email = String((emailEl && emailEl.value) || "").trim();
        const password = String((passwordEl && passwordEl.value) || "").trim();
        if (!email || !password) {
          setAuthMessage("Enter both email and password.", true);
          return;
        }
        const els = [emailEl, passwordEl, signinBtn].filter(Boolean);
        els.forEach((el) => { el.disabled = true; });
        try {
          setAuthMessage("Signing in…", false);
          await loginWithPassword(email, password);
          await loadInitialWorkspace();
          setStatus("Signed in.", false);
        } catch (err) {
          state.auth.status = "error";
          setAuthMessage(err.message || "Sign-in failed.", true);
          els.forEach((el) => { el.disabled = false; });
        }
      });
    }

    const authResetBtn = document.getElementById("auth-reset-btn");
    if (authResetBtn) {
      authResetBtn.addEventListener("click", () => withBusy(authResetBtn, "Sending…", async () => {
        const email = String(((document.getElementById("auth-email") || {}).value || "")).trim();
        if (!email) {
          setAuthMessage("Enter your email to request a password reset.", true);
          return;
        }
        try {
          await sendPasswordResetEmail(email);
          setAuthMessage("Reset link sent — check your inbox.", false);
        } catch (err) {
          setAuthMessage(err.message || "Password reset failed.", true);
        }
      }));
    }

    const authSetupLink = document.getElementById("auth-setup-link");
    if (authSetupLink) {
      authSetupLink.addEventListener("click", (ev) => {
        ev.preventDefault();
        window.location.hash = "#/setup";
        renderAuthShell();
      });
    }

    const accountSetupSigninLink = document.getElementById("account-setup-signin-link");
    if (accountSetupSigninLink) {
      accountSetupSigninLink.addEventListener("click", (ev) => {
        ev.preventDefault();
        window.location.hash = "";
        renderAuthShell();
      });
    }

    const accountSetupGoBtn = document.getElementById("account-setup-go-btn");
    if (accountSetupGoBtn) {
      accountSetupGoBtn.addEventListener("click", () => {
        window.location.hash = "";
        renderAuthShell();
      });
    }

    const accountSetupForm = document.getElementById("account-setup-form");
    if (accountSetupForm) {
      accountSetupForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const emailEl = document.getElementById("setup-email");
        const pwEl = document.getElementById("setup-password");
        const pw2El = document.getElementById("setup-password-confirm");
        const submitBtn = document.getElementById("account-setup-submit-btn");
        const statusEl = document.getElementById("account-setup-status");

        const showSetupStatus = (msg, isError) => {
          if (!statusEl) return;
          statusEl.textContent = msg;
          statusEl.style.color = isError ? "#ffd6d8" : "#d9ffeb";
          statusEl.hidden = !msg;
        };

        const email = (emailEl ? emailEl.value : "").trim().toLowerCase();
        const password = pwEl ? pwEl.value : "";
        const confirm = pw2El ? pw2El.value : "";

        showSetupStatus("", false);
        if (!email || !password) { showSetupStatus("Email and password are required.", true); return; }
        if (password.length < 8) { showSetupStatus("Password must be at least 8 characters.", true); return; }
        if (password !== confirm) { showSetupStatus("Passwords do not match.", true); return; }

        const formEls = [emailEl, pwEl, pw2El, submitBtn].filter(Boolean);
        formEls.forEach((el) => { el.disabled = true; });
        if (submitBtn) { submitBtn.textContent = "Creating account…"; submitBtn.classList.add("is-loading"); }

        try {
          const resp = await fetch("/api/auth/setup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) {
            const rawDetail = data.detail;
            const detail = typeof rawDetail === "string" ? rawDetail
              : Array.isArray(rawDetail) ? rawDetail.map((e) => (e && e.msg) || JSON.stringify(e)).join("; ")
              : "Account setup failed.";
            showSetupStatus(detail || "Account setup failed.", true);
            return;
          }
          showSetupStatus("Account created! Signing you in…", false);
          await loginWithPassword(email, password);
          renderSetupGateView(true, "", false);
          await loadInitialWorkspace();
          setStatus("Signed in.", false);
        } catch (err) {
          const errMsg = err instanceof Error ? err.message
            : (err && typeof err === "object" ? JSON.stringify(err) : String(err || ""));
          showSetupStatus(errMsg || "Something went wrong.", true);
        } finally {
          formEls.forEach((el) => { el.disabled = false; });
          if (submitBtn) { submitBtn.textContent = "Create Account"; submitBtn.classList.remove("is-loading"); }
        }
      });
    }

    window.addEventListener("hashchange", () => {
      if (!state.auth.client) return;
      if (state.auth.status === "authenticated" && !isSetupRoute()) return;
      renderAuthShell();
    });

    // FAB: deck library drawer toggle (tablet/phone)
    const fabDeckLibraryBtn = document.getElementById("fab-deck-library-btn");
    if (fabDeckLibraryBtn) {
      fabDeckLibraryBtn.addEventListener("click", () => toggleDeckLibraryDrawer());
    }
    // Close drawer when clicking outside it
    document.addEventListener("click", (ev) => {
      const sidebar = document.getElementById("deck-library-sidebar");
      if (sidebar && sidebar.classList.contains("is-drawer-open") && !sidebar.contains(ev.target) && ev.target !== fabDeckLibraryBtn) {
        toggleDeckLibraryDrawer(false);
      }
    });

    const accountSignoutBtn = document.getElementById("account-signout-btn");
    if (accountSignoutBtn) {
      accountSignoutBtn.addEventListener("click", async () => {
        await signOut("Signed out.");
        setStatus("Signed out.", false);
      });
    }

    // ── Account panel ────────────────────────────────────────────
    function initials(name) {
      return String(name || "?").trim().split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase() || "?";
    }

    function openAccountPanel() {
      const panel = document.getElementById("account-panel");
      if (!panel) return;
      const me = state.auth.me || {};

      // Populate header
      const avatarEl = document.getElementById("account-panel-avatar");
      if (avatarEl) avatarEl.textContent = initials(me.displayName || me.email || "BU");
      const panelNameEl = document.getElementById("account-panel-name");
      if (panelNameEl) panelNameEl.textContent = me.displayName || "Beta User";
      const panelEmailEl = document.getElementById("account-panel-email");
      if (panelEmailEl) panelEmailEl.textContent = me.email || "";

      // Name input
      const nameInput = document.getElementById("account-panel-name-input");
      if (nameInput) nameInput.value = me.displayName || "";
      const nameStatus = document.getElementById("account-panel-name-status");
      if (nameStatus) { nameStatus.hidden = true; nameStatus.textContent = ""; }

      // Info section
      const infoEmail = document.getElementById("account-panel-info-email");
      if (infoEmail) infoEmail.textContent = me.email || "—";
      const infoJoined = document.getElementById("account-panel-info-joined");
      if (infoJoined) {
        const d = me.createdAt ? new Date(me.createdAt) : null;
        infoJoined.textContent = d && !isNaN(d) ? d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "—";
      }
      const infoRole = document.getElementById("account-panel-info-role");
      if (infoRole) infoRole.textContent = me.role === "admin" ? "Admin" : "Beta member";

      // Library stats
      const lib = Array.isArray(state.library) ? state.library : [];
      const savedCount = document.getElementById("account-panel-saved-count");
      const builtCount = document.getElementById("account-panel-built-count");
      const publicCount = document.getElementById("account-panel-public-count");
      if (savedCount) savedCount.textContent = lib.filter((r) => r.bucket === "saved").length;
      if (builtCount) builtCount.textContent = lib.filter((r) => r.bucket === "built").length;
      if (publicCount) publicCount.textContent = lib.filter((r) => r.visibility === "public").length;

      panel.hidden = false;
      document.body.style.overflow = "hidden";
      setTimeout(() => nameInput && nameInput.focus(), 80);
    }

    function closeAccountPanel() {
      const panel = document.getElementById("account-panel");
      if (panel) panel.hidden = true;
      document.body.style.overflow = "";
    }

    const accountProfileBtn = document.getElementById("account-profile-btn");
    if (accountProfileBtn) {
      accountProfileBtn.addEventListener("click", openAccountPanel);
    }

    const accountPanelClose = document.getElementById("account-panel-close");
    if (accountPanelClose) {
      accountPanelClose.addEventListener("click", closeAccountPanel);
    }

    const accountPanelBackdrop = document.getElementById("account-panel-backdrop");
    if (accountPanelBackdrop) {
      accountPanelBackdrop.addEventListener("click", closeAccountPanel);
    }

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        const panel = document.getElementById("account-panel");
        if (panel && !panel.hidden) { closeAccountPanel(); ev.preventDefault(); }
      }
    });

    const accountPanelNameSave = document.getElementById("account-panel-name-save");
    if (accountPanelNameSave) {
      accountPanelNameSave.addEventListener("click", async () => {
        const nameInput = document.getElementById("account-panel-name-input");
        const nameStatus = document.getElementById("account-panel-name-status");
        const showStatus = (msg, isError) => {
          if (!nameStatus) return;
          nameStatus.textContent = msg;
          nameStatus.style.color = isError ? "#ffd6d8" : "#d9ffeb";
          nameStatus.hidden = !msg;
        };
        const newName = (nameInput ? nameInput.value : "").trim();
        if (!newName) { showStatus("Display name cannot be empty.", true); return; }
        await withBusy(accountPanelNameSave, "Saving…", async () => {
          try {
            const data = await api("/api/me/display-name", { method: "PUT", body: { displayName: newName } });
            if (data && data.user && data.user.displayName) {
              state.auth.me = { ...(state.auth.me || {}), displayName: data.user.displayName };
              renderAccountShell();
              // Refresh panel header
              const avatarEl = document.getElementById("account-panel-avatar");
              if (avatarEl) avatarEl.textContent = initials(data.user.displayName);
              const panelNameEl = document.getElementById("account-panel-name");
              if (panelNameEl) panelNameEl.textContent = data.user.displayName;
            }
            showStatus("Display name updated.", false);
          } catch (err) {
            showStatus(err.message || "Could not update display name.", true);
          }
        });
      });
    }

    const accountPanelSignout = document.getElementById("account-panel-signout");
    if (accountPanelSignout) {
      accountPanelSignout.addEventListener("click", async () => {
        closeAccountPanel();
        await signOut("Signed out.");
        setStatus("Signed out.", false);
      });
    }
    // ── End account panel ─────────────────────────────────────────

    const accountModelObservationBtn = document.getElementById("account-model-observation-btn");
    if (accountModelObservationBtn) {
      accountModelObservationBtn.addEventListener("click", () => {
        setWorkspaceTab("model-observation");
      });
    }

    Array.from(document.querySelectorAll("[data-workspace-tab]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        setWorkspaceTab(btn.getAttribute("data-workspace-tab") || "deck");
      });
    });

    Array.from(document.querySelectorAll("[data-discover-tab]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        setDiscoverTab(btn.getAttribute("data-discover-tab") || "meta");
      });
    });

    const deckNameInput = document.getElementById("deck-name");
    if (deckNameInput) {
      deckNameInput.addEventListener("input", () => {
        state.deck.name = String(deckNameInput.value || "").trim() || "Untitled Deck";
        updateDeckSaveState();
      });
    }

    const deckBucketSelect = document.getElementById("deck-bucket-select");
    if (deckBucketSelect) {
      deckBucketSelect.addEventListener("change", () => {
        state.editor.bucket = normalizeLibraryBucket(deckBucketSelect.value);
        state.ui.deckReservationMode = state.editor.bucket === "built" ? "built" : "";
        renderDeckWorkbench();
        updateDeckSaveState();
      });
    }

    const deckVisibilitySelect = document.getElementById("deck-visibility-select");
    if (deckVisibilitySelect) {
      deckVisibilitySelect.addEventListener("change", () => {
        state.editor.visibility = normalizeDeckVisibility(deckVisibilitySelect.value);
        updateDeckSaveState();
      });
    }

    const formatSelect = document.getElementById("deck-format-select");
    if (formatSelect) {
      formatSelect.addEventListener("change", async () => {
        const nextFormat = String(formatSelect.value || "constructed").trim() || "constructed";
        if (nextFormat === state.deck.format) return;
        state.deck.format = nextFormat;
        try {
          await refreshEligibility(state.deck.legendTitle, { applyRecommended: false, inferChampion: true, validate: true });
          await refreshAutoBuilderEligibility(state.autoBuilder.legendTitle, { render: false });
          await refreshMetaSearchResults();
          updateDeckSaveState();
          setStatus(`Format set to ${nextFormat}.`, false);
        } catch (err) {
          setStatus(err.message || "Could not switch format.", true);
        }
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
      mainSearchInput.addEventListener("input", debounce(() => renderMainSearchResults(), 180));
      mainSearchInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
        }
      });
    }

    const sideboardSearchBtn = document.getElementById("sideboard-search-btn");
    if (sideboardSearchBtn) {
      sideboardSearchBtn.addEventListener("click", () => {
        const input = document.getElementById("sideboard-search");
        if (!input) return;
        input.value = "";
        renderSideboardList();
      });
    }

    const sideboardSearchInput = document.getElementById("sideboard-search");
    if (sideboardSearchInput) {
      sideboardSearchInput.addEventListener("input", debounce(() => renderSideboardList(), 180));
      sideboardSearchInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") ev.preventDefault();
      });
    }

    const sideboardAddBtn = document.getElementById("sideboard-add-btn");
    if (sideboardAddBtn) {
      sideboardAddBtn.addEventListener("click", () => {
        openPicker("sideboard", 0);
      });
    }

    bindMainDeckDropZone();

    const pickerClose = document.getElementById("picker-close-btn");
    if (pickerClose) pickerClose.addEventListener("click", closePicker);

    const pickerSearch = document.getElementById("picker-search-input");
    if (pickerSearch) {
      pickerSearch.addEventListener("input", debounce(() => renderPickerGrid(), 180));
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

    const deckImportOpenBtn = document.getElementById("deck-import-open-btn");
    if (deckImportOpenBtn) deckImportOpenBtn.addEventListener("click", openDeckImportModal);

    const deckImportCloseBtn = document.getElementById("deck-import-close-btn");
    if (deckImportCloseBtn) deckImportCloseBtn.addEventListener("click", closeDeckImportModal);

    const deckImportModal = document.getElementById("deck-import-modal");
    if (deckImportModal) {
      deckImportModal.addEventListener("click", (ev) => {
        if (ev.target === deckImportModal) closeDeckImportModal();
      });
    }

    const metaDetailClose = document.getElementById("meta-detail-close-btn");
    if (metaDetailClose) metaDetailClose.addEventListener("click", closeMetaDetailModal);
    const metaDetailModal = document.getElementById("meta-detail-modal");
    if (metaDetailModal) {
      metaDetailModal.addEventListener("click", (ev) => {
        if (ev.target === metaDetailModal) closeMetaDetailModal();
      });
    }
    const metaDetailUse = document.getElementById("meta-detail-use-btn");
    if (metaDetailUse) {
      metaDetailUse.addEventListener("click", () => withBusy(metaDetailUse, "Loading…", async () => {
        try {
          await useDiscoverDeck(state.ui.metaDetailSource, state.ui.metaDetailIndex);
          closeMetaDetailModal();
        } catch (err) {
          setStatus(err.message || "Could not load deck.", true);
        }
      }));
    }
    const metaDetailWizard = document.getElementById("meta-detail-wizard-btn");
    if (metaDetailWizard) {
      metaDetailWizard.addEventListener("click", () => withBusy(metaDetailWizard, "Opening...", async () => {
        try {
          await bringDiscoverDeckToWizard(state.ui.metaDetailSource, state.ui.metaDetailIndex);
        } catch (err) {
          setStatus(err.message || "Could not bring deck to wizard.", true);
        }
      }));
    }
    const metaDetailSave = document.getElementById("meta-detail-save-btn");
    if (metaDetailSave) {
      metaDetailSave.addEventListener("click", () => withBusy(metaDetailSave, "Saving…", async () => {
        try {
          await saveDiscoverDeck(state.ui.metaDetailSource, state.ui.metaDetailIndex);
          setStatus("Deck saved to library.", false);
        } catch (err) {
          setStatus(err.message || "Could not save deck.", true);
        }
      }));
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
          const importPayload = await importCollectionCsv();
          await refreshMetaSearchResults();
          const summary = importPayload && importPayload.importSummary;
          if (summary) {
            const msg = `Imported ${summary.imported} card${summary.imported !== 1 ? "s" : ""}` +
              (summary.failed ? `, ${summary.failed} skipped` : "") +
              (Array.isArray(summary.errors) && summary.errors.length ? `. Issues: ${summary.errors.slice(0, 2).join("; ")}` : "");
            setStatus(msg, summary.failed > 0);
          } else {
            setStatus("Collection file imported.", false);
          }
        } catch (err) {
          setStatus(err.message || "Collection import failed.", true);
        } finally {
          collectionFileInput.value = "";
        }
      });
    }

    const collectionExportJsonBtn = document.getElementById("collection-export-json-btn");
    if (collectionExportJsonBtn) {
      collectionExportJsonBtn.addEventListener("click", async () => {
        try {
          await exportCollection("json");
          setStatus("Collection JSON exported.", false);
        } catch (err) {
          setStatus(err.message || "Collection export failed.", true);
        }
      });
    }

    const collectionExportCsvBtn = document.getElementById("collection-export-csv-btn");
    if (collectionExportCsvBtn) {
      collectionExportCsvBtn.addEventListener("click", async () => {
        try {
          await exportCollection("csv");
          setStatus("Collection CSV exported.", false);
        } catch (err) {
          setStatus(err.message || "Collection export failed.", true);
        }
      });
    }

    const collectionResetBtn = document.getElementById("collection-reset-btn");
    if (collectionResetBtn) {
      collectionResetBtn.addEventListener("click", async () => {
        try {
          await resetCollection();
          await refreshMetaSearchResults();
          setStatus("Collection reset.", false);
        } catch (err) {
          setStatus(err.message || "Collection reset failed.", true);
        }
      });
    }

    const collectionSearchInput = document.getElementById("collection-search-input");
    if (collectionSearchInput) {
      collectionSearchInput.addEventListener("input", debounce(() => {
        state.ui.collectionSearch = String(collectionSearchInput.value || "").trim();
        rerenderCollectionFromState();
      }, 180));
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
        const wasEdit = Boolean(state.ui.collectionEditMode);
        state.ui.collectionEditMode = !state.ui.collectionEditMode;
        rerenderCollectionFromState();
        if (wasEdit && Object.keys(collectionPendingPatch).length) {
          flushCollectionPending()
            .then(() => setStatus("Collection saved.", false))
            .catch((err) => setStatus(err.message || "Collection save failed.", true));
        }
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

    const deckAnalyzeBtn = document.getElementById("deck-analyze-btn");
    if (deckAnalyzeBtn) {
      deckAnalyzeBtn.addEventListener("click", async () => {
        try {
          await runAnalysis();
        } catch (err) {
          setStatus(err.message || "Analysis failed.", true);
        }
      });
    }

    const deckAutoCompleteBtn = document.getElementById("deck-auto-complete-btn");
    if (deckAutoCompleteBtn) {
      deckAutoCompleteBtn.addEventListener("click", () => withBusy(deckAutoCompleteBtn, "Working…", async () => {
        try {
          const response = await runAutoBuilderCompletion();
          if (!response || !response.bestCandidate || !response.bestCandidate.deck) {
            setStatus("Auto Builder did not find a completion candidate.", true);
            return;
          }
          await writeDeckToForm(response.bestCandidate.deck);
          setStatus(`Auto-completed deck with ${response.bestCandidate.winConditionLabel || "learned"} plan.`, false);
        } catch (err) {
          setStatus(err.message || "Auto-complete failed.", true);
        }
      }));
    }

    const replacementPlanBtn = document.getElementById("deck-replacement-plan-btn");
    if (replacementPlanBtn) {
      replacementPlanBtn.addEventListener("click", () => withBusy(replacementPlanBtn, "Working…", async () => {
        try {
          await runAutoBuilderCompletion();
          setWorkspaceTab("auto-builder");
          setStatus("Loaded best replacement plan into Auto Builder.", false);
        } catch (err) {
          setStatus(err.message || "Replacement planning failed.", true);
        }
      }));
    }

    const deckSaveBtn = document.getElementById("deck-save-btn");
    if (deckSaveBtn) {
      deckSaveBtn.addEventListener("click", () => withBusy(deckSaveBtn, "Saving…", async () => {
        try {
          await saveCurrentDeckToLibrary();
          if (state.lastValidation && !state.lastValidation.is_valid) {
            setStatus("Deck saved (currently illegal).", true);
          } else {
            setStatus("Deck saved to library.", false);
          }
        } catch (err) {
          setStatus(err.message || "Could not save deck.", true);
        }
      }));
    }

    const deckToWizardBtn = document.getElementById("deck-to-wizard-btn");
    if (deckToWizardBtn) {
      deckToWizardBtn.addEventListener("click", () => withBusy(deckToWizardBtn, "Opening...", async () => {
        try {
          await bringBuilderDeckToWizard();
        } catch (err) {
          setStatus(err.message || "Could not bring deck to wizard.", true);
        }
      }));
    }

    const deckExportBtn = document.getElementById("deck-export-btn");
    if (deckExportBtn) {
      deckExportBtn.addEventListener("click", () => {
        const deck = currentDeckFromForm();
        downloadJson(`${(deck.name || "deck").replace(/\s+/g, "-").toLowerCase()}.json`, deck);
        setStatus("Deck exported.", false);
      });
    }

    const deckClearBtn = document.getElementById("deck-clear-btn");
    if (deckClearBtn) {
      deckClearBtn.addEventListener("click", () => {
        showConfirmModal({
          title: "Clear Deck",
          body: "Clear the current deck from the worktable? Unsaved changes will be lost.",
          confirmLabel: "Clear",
          onConfirm: async () => {
            try {
              await clearDeckWorkbench();
              setStatus("Deck worktable cleared.", false);
            } catch (err) {
              setStatus(err.message || "Could not clear deck.", true);
            }
          }
        });
      });
    }

    const deckImportBtn = document.getElementById("deck-import-btn");
    if (deckImportBtn) {
      deckImportBtn.addEventListener("click", async () => {
        const input = document.getElementById("deck-import-text");
        const raw = String((input && input.value) || "").trim();
        if (!raw) {
          setStatus("Paste JSON into the import box.", true);
          return;
        }
        try {
          const parsed = JSON.parse(raw);
          const deck = parsed.deck || parsed;
          await writeDeckToForm(deck);
          if (input) input.value = "";
          closeDeckImportModal();
          setStatus("Deck imported into builder.", false);
        } catch (err) {
          setStatus(err.message || "Invalid JSON.", true);
        }
      });
    }

    const deckImportFileInput = document.getElementById("deck-import-file");
    const deckImportFilePickBtn = document.getElementById("deck-import-file-pick-btn");
    const deckImportFileName = document.getElementById("deck-import-file-name");
    const readDeckFile = async (file) => {
      if (!file) return;
      const text = await file.text();
      const input = document.getElementById("deck-import-text");
      if (input) input.value = text;
      if (deckImportFileName) deckImportFileName.textContent = file.name || "Deck JSON loaded.";
    };
    if (deckImportFilePickBtn && deckImportFileInput) {
      deckImportFilePickBtn.addEventListener("click", () => deckImportFileInput.click());
      deckImportFileInput.addEventListener("change", async () => {
        if (!deckImportFileInput.files || !deckImportFileInput.files.length) return;
        try {
          await readDeckFile(deckImportFileInput.files[0]);
        } catch (err) {
          setStatus(err.message || "Could not read deck file.", true);
        } finally {
          deckImportFileInput.value = "";
        }
      });
    }
    const deckImportDropzone = document.getElementById("deck-import-dropzone");
    if (deckImportDropzone) {
      const activateDrop = (on) => deckImportDropzone.classList.toggle("is-drop-target", Boolean(on));
      deckImportDropzone.addEventListener("dragover", (ev) => {
        ev.preventDefault();
        activateDrop(true);
      });
      deckImportDropzone.addEventListener("dragleave", () => activateDrop(false));
      deckImportDropzone.addEventListener("drop", async (ev) => {
        ev.preventDefault();
        activateDrop(false);
        const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
        if (!file) return;
        try {
          await readDeckFile(file);
        } catch (err) {
          setStatus(err.message || "Could not read deck file.", true);
        }
      });
    }

    const metaLoadBtn = document.getElementById("meta-load-btn");
    if (metaLoadBtn) {
      metaLoadBtn.addEventListener("click", async () => {
        try {
          await loadDiscoverResults();
          const count = state.ui.discoverTab === "community" ? state.communityDecks.length : state.metaDecks.length;
          setStatus(`Loaded ${count} discover results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load discover results.", true);
        }
      });
    }

    const metaSearchInput = document.getElementById("meta-search");
    if (metaSearchInput) {
      metaSearchInput.addEventListener("keydown", async (ev) => {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        try {
          await loadDiscoverResults();
          const count = state.ui.discoverTab === "community" ? state.communityDecks.length : state.metaDecks.length;
          setStatus(`Loaded ${count} discover results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load discover results.", true);
        }
      });
    }

    const metaRefreshBtn = document.getElementById("meta-refresh-btn");
    if (metaRefreshBtn) {
      metaRefreshBtn.addEventListener("click", async () => {
        try {
          await refreshMetaIndex();
          await loadMetaDecks();
          setStatus("Meta index refreshed.", false);
        } catch (err) {
          setStatus(err.message || "Meta refresh failed.", true);
        }
      });
    }

    const metaSortSelect = document.getElementById("meta-sort-by");
    if (metaSortSelect) {
      metaSortSelect.addEventListener("change", async () => {
        try {
          await loadMetaDecks();
          setStatus(`Loaded ${state.metaDecks.length} meta index results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load deck search results.", true);
        }
      });
    }

    const metaIncludeCollection = document.getElementById("meta-include-collection");
    if (metaIncludeCollection) {
      metaIncludeCollection.addEventListener("change", async () => {
        try {
          await loadMetaDecks();
          setStatus(`Loaded ${state.metaDecks.length} meta index results.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load deck search results.", true);
        }
      });
    }

    const commSortSelect = document.getElementById("community-sort-by");
    if (commSortSelect) {
      commSortSelect.addEventListener("change", async () => {
        try {
          await loadCommunityDecks();
          setStatus(`Loaded ${state.communityDecks.length} community decks.`, false);
        } catch (err) {
          setStatus(err.message || "Could not load community decks.", true);
        }
      });
    }

    const librarySearchBtn = document.getElementById("library-search-btn");
    if (librarySearchBtn) {
      librarySearchBtn.addEventListener("click", async () => {
        const input = document.getElementById("library-search");
        if (input) input.value = "";
        try {
          await loadLibrary();
        } catch (err) {
          setStatus(err.message || "Could not load your deck library.", true);
        }
      });
    }

    const librarySearchInput = document.getElementById("library-search");
    if (librarySearchInput) {
      librarySearchInput.addEventListener("keydown", async (ev) => {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        try {
          await loadLibrary();
        } catch (err) {
          setStatus(err.message || "Could not load your deck library.", true);
        }
      });
    }

    const rankingModeSelect = document.getElementById("auto-builder-ranking-mode");
    if (rankingModeSelect) {
      rankingModeSelect.value = state.autoBuilder.rankingMode;
      rankingModeSelect.addEventListener("change", () => {
        state.autoBuilder.rankingMode = String(rankingModeSelect.value || "collection").trim() || "collection";
      });
    }

    const strategyModeSelect = document.getElementById("auto-builder-strategy-mode");
    if (strategyModeSelect) {
      strategyModeSelect.value = state.autoBuilder.strategyMode;
      strategyModeSelect.addEventListener("change", () => {
        state.autoBuilder.strategyMode = String(strategyModeSelect.value || "hybrid").trim() || "hybrid";
      });
    }

    const autoBuilderLegendBtn = document.getElementById("auto-builder-legend-btn");
    if (autoBuilderLegendBtn) {
      autoBuilderLegendBtn.addEventListener("click", () => openPicker("auto-builder-legend", 0));
    }

    const autoBuilderLegendClear = document.getElementById("auto-builder-legend-clear");
    if (autoBuilderLegendClear) {
      autoBuilderLegendClear.addEventListener("click", async () => {
        state.autoBuilder.legendTitle = "";
        await refreshAutoBuilderEligibility("", { render: false });
        renderAutoBuilder();
      });
    }

    const autoBuilderChampionBtn = document.getElementById("auto-builder-champion-btn");
    if (autoBuilderChampionBtn) {
      autoBuilderChampionBtn.addEventListener("click", () => openPicker("auto-builder-champion", 0));
    }

    const autoBuilderChampionClear = document.getElementById("auto-builder-champion-clear");
    if (autoBuilderChampionClear) {
      autoBuilderChampionClear.addEventListener("click", () => {
        state.autoBuilder.chosenChampionTitle = "";
        renderAutoBuilder();
      });
    }

    const onlyBuildableInput = document.getElementById("auto-builder-only-buildable");
    if (onlyBuildableInput) {
      onlyBuildableInput.checked = Boolean(state.autoBuilder.onlyBuildable);
      onlyBuildableInput.addEventListener("change", () => {
        state.autoBuilder.onlyBuildable = Boolean(onlyBuildableInput.checked);
      });
    }

    const autoBuilderGenerateBtn = document.getElementById("auto-builder-generate-btn");
    if (autoBuilderGenerateBtn) {
      autoBuilderGenerateBtn.addEventListener("click", () => withBusy(autoBuilderGenerateBtn, "Generating…", async () => {
        try {
          await loadAutoBuilderRecommendations();
          setStatus(`Loaded ${state.autoBuilder.recommendations.length} auto-builder recommendations.`, false);
        } catch (err) {
          setStatus(err.message || "Auto Builder generation failed.", true);
        }
      }));
    }

    const autoBuilderRefreshStatusBtn = document.getElementById("auto-builder-refresh-status-btn");
    if (autoBuilderRefreshStatusBtn) {
      autoBuilderRefreshStatusBtn.addEventListener("click", () => withBusy(autoBuilderRefreshStatusBtn, "Checking…", async () => {
        try {
          await loadAutoBuilderStatus();
          setStatus("Auto Builder status refreshed.", false);
        } catch (err) {
          setStatus(err.message || "Could not refresh Auto Builder status.", true);
        }
      }));
    }

    const autoBuilderOpenManualBtn = document.getElementById("auto-builder-open-manual-btn");
    if (autoBuilderOpenManualBtn) {
      autoBuilderOpenManualBtn.addEventListener("click", async () => {
        try {
          await openAutoBuilderSelectionInManual();
        } catch (err) {
          setStatus(err.message || "Could not open auto-builder deck.", true);
        }
      });
    }

    const autoBuilderSaveBtn = document.getElementById("auto-builder-save-btn");
    if (autoBuilderSaveBtn) {
      autoBuilderSaveBtn.addEventListener("click", async () => {
        try {
          await saveAutoBuilderSelection();
        } catch (err) {
          setStatus(err.message || "Could not save auto-builder deck.", true);
        }
      });
    }

    const modelObservationRefreshBtn = document.getElementById("model-observation-refresh-btn");
    if (modelObservationRefreshBtn) {
      modelObservationRefreshBtn.addEventListener("click", async () => {
        try {
          await loadModelObservationOverview();
          setStatus("Model observation refreshed.", false);
        } catch (err) {
          setStatus(err.message || "Could not refresh model observation.", true);
        }
      });
    }

    const modelObservationSnapshotBtn = document.getElementById("model-observation-snapshot-btn");
    if (modelObservationSnapshotBtn) {
      modelObservationSnapshotBtn.addEventListener("click", async () => {
        try {
          const row = await snapshotModelObservationProduction();
          if (row) setStatus(`Saved production snapshot ${row.label || row.id || ""}.`, false);
        } catch (err) {
          setStatus(err.message || "Could not snapshot production model.", true);
        }
      });
    }

    const modelTrainingRunBtn = document.getElementById("model-training-run-btn");
    if (modelTrainingRunBtn) {
      modelTrainingRunBtn.addEventListener("click", async () => {
        try {
          const training = await startModelObservationTraining();
          setWorkspaceTab("model-observation");
          setStatus(`Started training job ${training.jobId || ""}.`, false);
        } catch (err) {
          setStatus(err.message || "Could not start model training.", true);
        }
      });
    }

    const modelTrainingRefreshBtn = document.getElementById("model-training-refresh-btn");
    if (modelTrainingRefreshBtn) {
      modelTrainingRefreshBtn.addEventListener("click", async () => {
        try {
          await loadModelObservationTrainingStatus();
          setStatus("Training status refreshed.", false);
        } catch (err) {
          setStatus(err.message || "Could not refresh training status.", true);
        }
      });
    }

    Array.from(
      document.querySelectorAll(
        "#model-training-label, #model-training-epochs"
      )
    ).forEach((input) => {
      const eventName = input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input";
      input.addEventListener(eventName, () => {
        readModelObservationForm();
      });
    });

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
        closeMetaDetailModal();
        closeDeckImportModal();
        hidePreview();
      }
    });

    const wizardResetBtn = document.getElementById("wizard-reset-btn");
    if (wizardResetBtn) {
      wizardResetBtn.addEventListener("click", () => {
        resetWizard();
      });
    }
  }

  // ── Deckbuilding Guided Wizard ───────────────────────────────────
  function getWizardOwnedQty(title, requiredQty) {
    const clean = canonicalTitle(title);
    if (!clean) return 0;
    const required = Math.max(0, Number(requiredQty || 0) || 0);
    if (state.wizard.transientCollection[clean] !== undefined) {
      let qty = Math.max(0, Number(state.wizard.transientCollection[clean] || 0) || 0);
      if (isWizardRuneCardTitle(clean) && required > 0) {
        qty = Math.max(qty, required);
      }
      return qty;
    }
    if (state.wizard.collectionAgnostic) {
      if (isWizardRuneCardTitle(clean) && required > 0) return required;
      return required > 0 ? required : wizardMainCopyCapForTitle(clean);
    }
    if (state.collection && state.collection[clean] !== undefined) {
      let qty = Math.max(0, Number(state.collection[clean] || 0) || 0);
      if (isWizardRuneCardTitle(clean) && required > 0) {
        qty = Math.max(qty, required);
      }
      return qty;
    }
    return 0;
  }

  function setWizardOwnedQty(title, qty) {
    const clean = canonicalTitle(title);
    if (!clean) return;
    state.wizard.transientCollection[clean] = Math.max(0, Number(qty || 0) || 0);
  }

  function wizardCollectionCardsMap(value, opts) {
    const includeZero = Boolean(opts && opts.includeZero);
    if (!value || typeof value !== "object") return {};
    const source = value.cards && typeof value.cards === "object" ? value.cards : value;
    const out = {};
    Object.entries(source || {}).forEach(([title, qty]) => {
      const clean = canonicalTitle(title);
      const amount = Math.max(0, Number(qty || 0) || 0);
      if (clean && (amount > 0 || includeZero)) out[clean] = amount;
    });
    return out;
  }

  function wizardAgnosticOwnedPool() {
    const out = {};
    (state.cards || []).forEach((card) => {
      const title = canonicalTitle(card && card.title);
      if (!title) return;
      if (isWizardRuneCardTitle(title)) {
        out[title] = Math.max(out[title] || 0, 12);
        return;
      }
      out[title] = Math.max(out[title] || 0, wizardMainCopyCapForTitle(title));
    });
    return out;
  }

  function wizardEffectiveCollection() {
    const merged = {};
    if (state.wizard.collectionAgnostic) {
      Object.assign(merged, wizardAgnosticOwnedPool());
    } else if (state.collection) {
      Object.assign(merged, wizardCollectionCardsMap(state.collection));
    }
    Object.assign(merged, wizardCollectionCardsMap(state.wizard.transientCollection, { includeZero: true }));
    return merged;
  }

  function wizardVisibleIteration() {
    return Math.max(1, Number(state.wizard.iteration || 0) || 0);
  }

  function wizardNextIterationNumber() {
    return wizardVisibleIteration() + 1;
  }

  function wizardMainDeckTitles() {
    const deck = state.wizard.deck || {};
    const seen = new Set();
    const out = [];
    Object.keys(deck.main || {}).forEach((title) => {
      const clean = canonicalTitle(title);
      const required = Math.max(0, Number((deck.main || {})[title] || 0) || 0);
      if (!clean || required <= 0 || seen.has(clean)) return;
      seen.add(clean);
      out.push(clean);
    });
    const champion = canonicalTitle(deck.chosenChampionTitle || "");
    if (champion && !seen.has(champion)) out.push(champion);
    return out;
  }

  function wizardMainInventoryMetrics() {
    const deck = state.wizard.deck || {};
    let required = 0;
    let owned = 0;
    let missingCards = 0;
    wizardMainDeckTitles().forEach((title) => {
      const needed = Math.max(0, Number((deck.main || {})[title] || (canonicalTitle(deck.chosenChampionTitle) === title ? 1 : 0)) || 0);
      if (needed <= 0) return;
      const have = Math.min(needed, getWizardOwnedQty(title, needed));
      required += needed;
      owned += have;
      if (have < needed) missingCards += 1;
    });
    return {
      required,
      owned,
      missingCards,
      completionPct: required > 0 ? (owned / required) * 100 : 100
    };
  }

  function wizardBaselineOwnedQty(title, requiredQty) {
    const clean = canonicalTitle(title);
    const required = Math.max(0, Number(requiredQty || 0) || 0);
    if (!clean) return 0;
    if (state.wizard.collectionAgnostic) return required;
    const fromCollection = wizardCollectionCardsMap(state.collection || {});
    return Math.min(required, Math.max(0, Number(fromCollection[clean] || 0) || 0));
  }

  function applyWizardPhysicalChecklistMode(enabled) {
    const deck = state.wizard.deck || {};
    wizardMainDeckTitles().forEach((title) => {
      const required = Math.max(0, Number((deck.main || {})[title] || (canonicalTitle(deck.chosenChampionTitle) === title ? 1 : 0)) || 0);
      if (required <= 0) return;
      setWizardOwnedQty(title, enabled ? 0 : wizardBaselineOwnedQty(title, required));
    });
  }

  function beginWizardDeckbuildingIteration() {
    state.wizard.iteration = 1;
    state.wizard.iterationHistory = [];
    state.wizard.lastRefinement = null;
    state.wizard.activeReplacementCard = null;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementNotice = "";
    state.wizard.physicalChecklistMode = false;
  }

  function getWizardMissingCount(title, requiredQty) {
    const required = Math.max(0, Number(requiredQty || 0) || 0);
    if (isWizardRuneCardTitle(title)) return 0;
    const owned = getWizardOwnedQty(title, required);
    return Math.max(0, required - owned);
  }

  function renderWizardPreservingChecklistScroll() {
    renderWizard({ preserveChecklistScroll: true });
  }

  function wizardPlaylistStorageKey() {
    const legend = canonicalTitle(state.wizard.deck.legendTitle || "");
    const userId = String((state.auth.me && (state.auth.me.id || state.auth.me.user_id)) || "local").trim() || "local";
    return `riftbound:wizard-playlist:${userId}:${legend}`;
  }

  function loadWizardPlaylistFromStorage() {
    const legend = canonicalTitle(state.wizard.deck.legendTitle || "");
    if (!legend || typeof localStorage === "undefined") return;
    try {
      const raw = localStorage.getItem(wizardPlaylistStorageKey());
      if (!raw) return;
      const rows = JSON.parse(raw);
      if (!Array.isArray(rows)) return;
      state.wizard.savedRecommendations = rows
        .filter((row) => row && row.card)
        .map((row) => ({
          card: canonicalTitle(row.card),
          required: Math.max(1, Number(row.required || 1) || 1),
          reason: String(row.reason || "").trim(),
          source: String(row.source || "").trim(),
          score: Number(row.score || 0) || 0,
          iteration: Number(row.iteration || 0) || 0,
          addedAt: Number(row.addedAt || 0) || 0
        }));
    } catch (err) {
      console.warn("Could not load wizard playlist:", err);
    }
  }

  function saveWizardPlaylistToStorage() {
    const legend = canonicalTitle(state.wizard.deck.legendTitle || "");
    if (!legend || typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(wizardPlaylistStorageKey(), JSON.stringify(state.wizard.savedRecommendations || []));
    } catch (err) {
      console.warn("Could not save wizard playlist:", err);
    }
  }

  function wizardEnumerateDeckRequirements(deck) {
    const rows = [];
    const push = (title, qty) => {
      const clean = canonicalTitle(title);
      const required = Math.max(0, Number(qty || 0) || 0);
      if (!clean || required <= 0) return;
      rows.push({ title: clean, required });
    };
    if (!deck) return rows;
    push(deck.legendTitle, 1);
    push(deck.chosenChampionTitle, 1);
    Object.entries(deck.main || {}).forEach(([title, qty]) => push(title, qty));
    Object.entries(deck.runes || {}).forEach(([title, qty]) => push(title, qty));
    Object.entries(deck.sideboard || {}).forEach(([title, qty]) => push(title, qty));
    (deck.battlefields || []).forEach((title) => {
      if (title) push(title, 1);
    });
    return rows;
  }

  function wizardDeckBuildMetrics(deck) {
    const slots = wizardEnumerateDeckRequirements(deck);
    let requiredTotal = 0;
    let ownedTotal = 0;
    let missingUnique = 0;
    slots.forEach(({ title, required }) => {
      requiredTotal += required;
      const owned = Math.min(required, getWizardOwnedQty(title, required));
      ownedTotal += owned;
      if (owned < required) missingUnique += 1;
    });
    const completionPct = requiredTotal > 0 ? (ownedTotal / requiredTotal) * 100 : 100;
    return {
      requiredTotal,
      ownedTotal,
      missingUnique,
      completionPct,
      isBuildable: missingUnique === 0
    };
  }

  function wizardDecksNearlyEqual(left, right) {
    const a = normalizeDeckPayload(left || {});
    const b = normalizeDeckPayload(right || {});
    const mapsEqual = (m1, m2) => {
      const keys = new Set([...Object.keys(m1 || {}), ...Object.keys(m2 || {})]);
      for (const key of keys) {
        if (Math.max(0, Number(m1[key] || 0) || 0) !== Math.max(0, Number(m2[key] || 0) || 0)) return false;
      }
      return true;
    };
    return (
      canonicalTitle(a.legendTitle) === canonicalTitle(b.legendTitle) &&
      canonicalTitle(a.chosenChampionTitle) === canonicalTitle(b.chosenChampionTitle) &&
      mapsEqual(a.main, b.main) &&
      mapsEqual(a.runes, b.runes) &&
      mapsEqual(a.sideboard, b.sideboard) &&
      (a.battlefields || []).map(canonicalTitle).join("|") === (b.battlefields || []).map(canonicalTitle).join("|")
    );
  }

  function wizardMainCopyCapForTitle(title) {
    const card = lookupCard(title);
    const fromWizard = state.wizard.eligibility && state.wizard.eligibility.mainCopyLimit;
    const base = Math.max(1, Number(fromWizard || state.eligibility.mainCopyLimit || 3) || 3);
    if (card && card.isUnique) return 1;
    return base;
  }

  function capWizardDeckMainCopies(deck) {
    const src = normalizeDeckPayload(deck || {});
    const capped = {};
    Object.entries(src.main || {}).forEach(([title, qty]) => {
      const clean = canonicalTitle(title);
      const cap = wizardMainCopyCapForTitle(clean);
      const amount = Math.min(Math.max(0, Number(qty || 0) || 0), cap);
      if (clean && amount > 0) capped[clean] = amount;
    });
    src.main = capped;
    return src;
  }

  async function validateWizardDeckPayload(deck) {
    return api("/api/decks/validate", {
      method: "POST",
      body: { deck: normalizeDeckPayload(deck || {}) }
    });
  }

  function buildWizardSwapCandidate(originalCard, replacementCard) {
    const deck = capWizardDeckMainCopies(state.wizard.deck);
    const original = canonicalTitle(originalCard);
    const replacement = canonicalTitle(replacementCard);
    if (!original || !replacement) return deck;

    const replaceInMap = (map, strictOwned) => {
      if (!map || map[original] === undefined) return map || {};
      const next = { ...(map || {}) };
      const qty = Math.max(0, Number(next[original] || 0) || 0);
      delete next[original];
      const cap = strictOwned
        ? Math.min(wizardMainCopyCapForTitle(replacement), getWizardOwnedQty(replacement, qty))
        : qty;
      const replacementQty = Math.min(qty, Math.max(0, Number(cap || 0) || 0));
      if (replacementQty > 0) next[replacement] = replacementQty;
      return next;
    };

    deck.main = replaceInMap(deck.main, true);
    deck.runes = replaceInMap(deck.runes, false);
    deck.sideboard = replaceInMap(deck.sideboard, false);
    deck.battlefields = (deck.battlefields || []).map((title) => canonicalTitle(title) === original ? replacement : title);
    return capWizardDeckMainCopies(deck);
  }

  function wizardDiffSummaryHtml(diff) {
    if (!diff) return "";
    const rows = [];
    (diff.added || []).forEach((row) => rows.push(`Added ${row.qty || 0}x ${row.card || ""}`));
    (diff.removed || []).forEach((row) => rows.push(`Removed ${row.qty || 0}x ${row.card || ""}`));
    (diff.qtyChanges || diff.qty_changes || []).forEach((row) => rows.push(`${row.card || ""}: ${row.before || 0}x -> ${row.after || 0}x`));
    if (!rows.length) return "";
    const shown = rows.slice(0, 12).map((line) => `<li>${esc(line)}</li>`).join("");
    const more = rows.length > 12 ? `<li class="muted">and ${esc(rows.length - 12)} more</li>` : "";
    return `<ul class="wizard-diff-list">${shown}${more}</ul>`;
  }

  function wizardLegalityStripHtml(validation) {
    if (!validation) return "";
    const issues = Array.isArray(validation.issues) ? validation.issues : [];
    const codes = issues.slice(0, 3).map((issue) => issue && issue.code).filter(Boolean).join(", ");
    const valid = Boolean(validation.is_valid);
    return (
      `<div class="wizard-legality-strip ${valid ? "is-legal" : "is-illegal"}">` +
      `<strong>${valid ? "Legal" : "Illegal"}</strong>` +
      `<span>${valid ? "Validated deck list" : esc(codes || validation.summary || "Validation failed")}</span>` +
      `</div>`
    );
  }

  function appendWizardPlaylistEntries(entries) {
    const list = Array.isArray(entries) ? entries : [];
    const seen = new Set((state.wizard.savedRecommendations || []).map((row) => canonicalTitle(row.card)));
    list.forEach((entry) => {
      const card = canonicalTitle(entry && entry.card);
      const required = Math.max(1, Number((entry && entry.required) || 1) || 1);
      if (!card || seen.has(card)) return;
      const owned = getWizardOwnedQty(card, required);
      if (owned >= required) return;
      seen.add(card);
      state.wizard.savedRecommendations.push({
        card,
        required,
        reason: String((entry && entry.reason) || "Future upgrade for this legend").trim(),
        source: String((entry && entry.source) || "").trim(),
        score: Number((entry && entry.score) || 0) || 0,
        iteration: Number(state.wizard.iteration || 0) || 0,
        addedAt: Date.now()
      });
    });
    state.wizard.savedRecommendations.sort((a, b) => (b.score || 0) - (a.score || 0) || (b.addedAt || 0) - (a.addedAt || 0));
    saveWizardPlaylistToStorage();
  }

  function collectWizardPlaylistCandidates(hybridRes, buildableRes) {
    const entries = [];
    const pushMissing = (missingCards, reason, source, score) => {
      (missingCards || []).forEach((row) => {
        const card = row && (row.card || row.title);
        if (!card) return;
        entries.push({
          card,
          required: Math.max(1, Number(row.missing || row.missingCopies || 1) || 1),
          reason,
          source,
          score: Number(score || 0) || 0
        });
      });
    };

    (hybridRes && hybridRes.recommendations ? hybridRes.recommendations : []).slice(0, 6).forEach((rec) => {
      const label = rec.winConditionLabel || rec.archetypeName || "synergy";
      pushMissing(rec.missingCards, `Improves ${label} package`, "model-upgrade", rec.competitiveScore || rec.rankingScore || 0);
      (rec.replacementSuggestions || []).slice(0, 4).forEach((swap) => {
        const card = swap && (swap.card || swap.to || swap.replacement);
        if (!card) return;
        entries.push({
          card,
          required: 1,
          reason: swap.reason || "Suggested swap from model",
          source: "replacement",
          score: rec.competitiveScore || 0
        });
      });
    });

    (buildableRes && buildableRes.recommendations ? buildableRes.recommendations : []).slice(1, 5).forEach((rec) => {
      pushMissing(rec.missingCards, "Alternative build path", "buildable-alt", rec.competitiveScore || 0);
    });

    const optimal = state.wizard.optimalTargetDeck;
    if (optimal) {
      wizardEnumerateDeckRequirements(optimal).forEach(({ title, required }) => {
        const owned = getWizardOwnedQty(title, required);
        if (owned < required) {
          entries.push({
            card: title,
            required: required - owned,
            reason: "From original optimal template",
            source: "optimal-target",
            score: 0.99
          });
        }
      });
    }

    appendWizardPlaylistEntries(entries);
  }

  function canFinalizeWizard() {
    const metrics = wizardDeckBuildMetrics(state.wizard.deck);
    if (metrics.isBuildable) return true;
    const history = state.wizard.iterationHistory || [];
    if (history.length >= 2) {
      const last = history[history.length - 1];
      const prev = history[history.length - 2];
      if (Math.abs(Number(last.afterCompletionPct || 0) - Number(prev.afterCompletionPct || 0)) < 1) return true;
    }
    return Number(state.wizard.iteration || 0) >= 1;
  }

  function wizardPlaylistPanelHtml() {
    const rows = Array.isArray(state.wizard.savedRecommendations) ? state.wizard.savedRecommendations : [];
    if (!rows.length) {
      return `<p class="muted wizard-playlist-empty">Saved upgrade ideas appear here as you refine — like playlist recommendations for your legend.</p>`;
    }
    const items = rows.slice(0, 12).map((row) => {
      const info = lookupCard(row.card);
      const owned = getWizardOwnedQty(row.card, row.required);
      const stillNeed = Math.max(0, row.required - owned);
      return (
        `<li class="wizard-playlist-item">` +
        `<div class="wizard-playlist-item-main">` +
        `<strong>${esc(row.card)}</strong>` +
        `<span class="muted">Need ${stillNeed} more · ${esc(row.reason || "Upgrade")}</span>` +
        `</div>` +
        `<span class="wizard-playlist-tag">${esc(info ? cardMetaLine(info) : row.source || "upgrade")}</span>` +
        `</li>`
      );
    }).join("");
    return `<ul class="wizard-playlist-list">${items}</ul>`;
  }

  function wizardIterationBannerHtml() {
    const metrics = wizardDeckBuildMetrics(state.wizard.deck);
    const iteration = wizardVisibleIteration();
    const last = state.wizard.lastRefinement;
    const pct = Math.round(metrics.completionPct);
    const note = last && last.message ? `<p class="muted wizard-iteration-note">${esc(last.message)}</p>` : "";
    const legality = last && last.validation ? wizardLegalityStripHtml(last.validation) : "";
    const diff = last && last.diff ? wizardDiffSummaryHtml(last.diff) : "";
    return (
      `<div class="wizard-iteration-banner">` +
      `<div class="wizard-iteration-metrics">` +
      `<span class="wizard-iteration-round">Iteration ${iteration}</span>` +
      `<span class="wizard-iteration-pct${metrics.isBuildable ? " is-complete" : ""}">${pct}% collection match</span>` +
      `${metrics.isBuildable ? `<span class="wizard-iteration-badge">Fully buildable</span>` : ""}` +
      `</div>` +
      `${legality}` +
      `${note}` +
      `${diff}` +
      `</div>`
    );
  }

  async function runWizardRefinement() {
    state.wizard.step = "refining";
    state.wizard.completeData = null;
    renderWizard();

    const deck = capWizardDeckMainCopies(state.wizard.deck);
    state.wizard.deck = deck;
    const legend = String(deck.legendTitle || "").trim();
    const champion = String(deck.chosenChampionTitle || "").trim();
    const collection = wizardEffectiveCollection();
    const beforeMetrics = wizardDeckBuildMetrics(deck);

    try {
      const response = await api("/api/wizard/solve", {
        method: "POST",
        body: {
          legendTitle: legend,
          chosenChampionTitle: champion,
          format: state.wizard.format || deck.format || "constructed",
          owned: collection,
          referenceDeck: state.wizard.optimalTargetDeck || state.wizard.targetDeck || deck,
          currentDeck: deck,
          mode: "owned_only",
          maxIterations: 1,
          collectionAgnostic: state.wizard.collectionAgnostic || false
        }
      });

      appendWizardPlaylistEntries(response.playlist || []);

      let deckChanged = false;
      const appliedScore = Number((response.metrics && response.metrics.competitiveScore) || 0) || 0;
      const validation = response.validation || null;

      if (response.deck && validation && validation.is_valid) {
        const candidateDeck = capWizardDeckMainCopies(response.deck);
        candidateDeck.name = deck.name || candidateDeck.name;
        candidateDeck.source = "wizard";
        candidateDeck.format = state.wizard.format || candidateDeck.format;
        const candidateMetrics = wizardDeckBuildMetrics(candidateDeck);
        const shouldApply = candidateMetrics.completionPct >= beforeMetrics.completionPct - 0.25;
        if (shouldApply && !wizardDecksNearlyEqual(deck, candidateDeck)) {
          state.wizard.deck = candidateDeck;
          deckChanged = true;
        }
      }

      const afterMetrics = wizardDeckBuildMetrics(state.wizard.deck);
      let displayedValidation = validation;
      if (!deckChanged && (!validation || !validation.is_valid)) {
        try {
          displayedValidation = await validateWizardDeckPayload(state.wizard.deck);
        } catch (_err) {
          displayedValidation = validation;
        }
      }
      const status = String(response.solverStatus || "").trim() || "feasible";
      const pctGain = afterMetrics.completionPct - beforeMetrics.completionPct;
      state.wizard.iteration = wizardNextIterationNumber();
      state.wizard.iterationHistory.push({
        iteration: state.wizard.iteration,
        beforeCompletionPct: beforeMetrics.completionPct,
        afterCompletionPct: afterMetrics.completionPct,
        deckChanged,
        isBuildable: afterMetrics.isBuildable,
        competitiveScore: appliedScore,
        solverStatus: status
      });

      let message = "";
      if (status === "infeasible_owned_only") {
        message = "Could not find a full 40-card legal build from the owned cards in this collection data; kept your current deck and saved upgrade ideas.";
      } else if (validation && !validation.is_valid) {
        const firstIssue = Array.isArray(validation.issues) && validation.issues[0] ? validation.issues[0].code : "VALIDATION";
        message = `Solver returned an illegal list (${firstIssue}); kept your current deck and saved upgrade ideas.`;
      } else if (deckChanged) {
        const clusterCount = Array.isArray(response.replacementClusters) ? response.replacementClusters.length : 0;
        message = clusterCount
          ? `Applied a legal owned-card replacement cluster at ${Math.round(afterMetrics.completionPct)}% collection match (iteration ${state.wizard.iteration}).`
          : `Applied a legal ${Math.round(afterMetrics.completionPct)}% collection match (iteration ${state.wizard.iteration}).`;
      } else if (Math.abs(pctGain) < 1) {
        message = `Plateau reached at ${Math.round(afterMetrics.completionPct)}% collection match; no legal owned-only improvement found.`;
      } else {
        message = `Kept your legal list at ${Math.round(afterMetrics.completionPct)}% collection match.`;
      }

      state.wizard.lastRefinement = {
        deckChanged,
        buildablePct: afterMetrics.completionPct,
        isBuildable: afterMetrics.isBuildable,
        competitiveScore: appliedScore,
        solverStatus: status,
        validation: displayedValidation,
        diff: deckChanged ? response.diff || null : null,
        replacementClusters: response.replacementClusters || [],
        message
      };

      state.wizard.step = "deckbuilding";
      state.wizard.activeReplacementCard = null;
      state.wizard.activeReplacementOptions = [];
      state.wizard.activeReplacementNotice = "";
      renderWizard();
      setStatus(state.wizard.lastRefinement.message, Boolean(displayedValidation && !displayedValidation.is_valid));
    } catch (err) {
      console.error("Wizard refinement failed:", err);
      state.wizard.step = "deckbuilding";
      renderWizard();
      setStatus(err.message || "Could not refine deck for your collection.", true);
    }
  }

  async function runWizardRefinementLegacy() {
    state.wizard.step = "refining";
    state.wizard.completeData = null;
    renderWizard();

    const deck = state.wizard.deck;
    const legend = String(deck.legendTitle || "").trim();
    const champion = String(deck.chosenChampionTitle || "").trim();
    const collection = state.wizard.transientCollection || {};
    const beforeMetrics = wizardDeckBuildMetrics(deck);

    try {
      const [buildableRes, hybridRes] = await Promise.all([
        api("/api/auto-builder/recommendations", {
          method: "POST",
          body: {
            top: 16,
            rankingMode: "collection",
            strategyMode: "hybrid",
            legendTitle: legend,
            chosenChampionTitle: champion,
            collectionOverride: collection,
            onlyBuildable: true,
            minResults: 8
          }
        }),
        api("/api/auto-builder/recommendations", {
          method: "POST",
          body: {
            top: 8,
            rankingMode: "hybrid",
            strategyMode: "hybrid",
            legendTitle: legend,
            chosenChampionTitle: champion,
            collectionOverride: collection,
            onlyBuildable: false
          }
        })
      ]);

      collectWizardPlaylistCandidates(hybridRes, buildableRes);

      const buildable = Array.isArray(buildableRes.recommendations) && buildableRes.recommendations.length
        ? buildableRes.recommendations[0]
        : null;
      let deckChanged = false;
      let appliedScore = 0;

      if (buildable && buildable.deck) {
        const candidateDeck = normalizeDeckPayload(buildable.deck);
        candidateDeck.name = deck.name || candidateDeck.name;
        candidateDeck.source = "wizard";
        candidateDeck.format = state.wizard.format || candidateDeck.format;
        const candidateMetrics = {
          completionPct: Number(buildable.completionPct || 0) || 0,
          isBuildable: Boolean(buildable.isBuildable),
          competitiveScore: Number(buildable.competitiveScore || 0) || 0
        };
        const shouldApply =
          candidateMetrics.isBuildable ||
          candidateMetrics.completionPct > beforeMetrics.completionPct + 0.25;
        if (shouldApply && !wizardDecksNearlyEqual(deck, candidateDeck)) {
          state.wizard.deck = candidateDeck;
          deckChanged = true;
          appliedScore = candidateMetrics.competitiveScore;
        }
      }

      const afterMetrics = wizardDeckBuildMetrics(state.wizard.deck);
      state.wizard.iteration = wizardNextIterationNumber();
      state.wizard.iterationHistory.push({
        iteration: state.wizard.iteration,
        beforeCompletionPct: beforeMetrics.completionPct,
        afterCompletionPct: afterMetrics.completionPct,
        deckChanged,
        isBuildable: afterMetrics.isBuildable,
        competitiveScore: appliedScore
      });

      state.wizard.lastRefinement = {
        deckChanged,
        buildablePct: afterMetrics.completionPct,
        isBuildable: afterMetrics.isBuildable,
        competitiveScore: appliedScore,
        message: deckChanged
          ? `Applied a stronger ${Math.round(afterMetrics.completionPct)}% collection match (iteration ${state.wizard.iteration}).`
          : buildable
            ? `Kept your list — already near the best ${Math.round(afterMetrics.completionPct)}% match we found (iteration ${state.wizard.iteration}).`
            : `No better fully-owned list yet; saved upgrade ideas below for iteration ${state.wizard.iteration}.`
      };

      state.wizard.step = "deckbuilding";
      state.wizard.activeReplacementCard = null;
      state.wizard.activeReplacementOptions = [];
      renderWizard();
      setStatus(state.wizard.lastRefinement.message, false);
    } catch (err) {
      console.error("Wizard refinement failed:", err);
      state.wizard.step = "deckbuilding";
      renderWizard();
      setStatus(err.message || "Could not refine deck for your collection.", true);
    }
  }

  function renderWizardRefining() {
    const container = document.getElementById("wizard-container");
    if (!container) return;
    const round = wizardNextIterationNumber();
    container.innerHTML = `
      <div class="wizard-refining-pane">
        <div class="loader wizard-refining-loader"></div>
        <h4>Finding the strongest deck for your collection</h4>
        <p class="muted">Iteration ${esc(String(round))}: rerunning the model with the cards you own and saving upgrade ideas for later.</p>
      </div>
    `;
  }

  async function finalizeWizardDeck() {
    const validation = await validateWizardDeckPayload(state.wizard.deck);
    if (!validation || !validation.is_valid) {
      const firstIssue = validation && Array.isArray(validation.issues) && validation.issues[0]
        ? validation.issues[0].code
        : "VALIDATION";
      state.wizard.lastRefinement = {
        ...(state.wizard.lastRefinement || {}),
        validation,
        message: `Finalize blocked because the current deck is illegal (${firstIssue}).`
      };
      renderWizardPreservingChecklistScroll();
      setStatus(state.wizard.lastRefinement.message, true);
      return;
    }
    state.wizard.lastRefinement = {
      ...(state.wizard.lastRefinement || {}),
      validation
    };
    state.wizard.step = "complete";
    state.wizard.completeData = null;
    renderWizard();
  }

  function wizardLegendChampionTagSet(legendTitle) {
    const legend = lookupCard(legendTitle || "");
    const tags = legend && Array.isArray(legend.championTags) ? legend.championTags : [];
    return new Set(tags.map((tag) => String(tag || "").trim()).filter(Boolean));
  }

  function isWizardRuneCardTitle(title) {
    const card = lookupCard(title);
    if (!card) return false;
    const cardType = String(card.cardType || "").trim();
    const superType = String(card.superType || "").trim();
    return cardType === "Rune" || superType === "Rune";
  }

  function assumeWizardLegendsOwned() {
    fallbackLegendCards().forEach((card) => {
      const title = canonicalTitle(card.title);
      if (title) state.wizard.transientCollection[title] = 1;
    });
  }

  function assumeWizardRunesOwned() {
    (state.cards || []).forEach((card) => {
      if (!isWizardRuneCardTitle(card.title)) return;
      const title = canonicalTitle(card.title);
      if (title) state.wizard.transientCollection[title] = Math.max(12, Number(state.wizard.transientCollection[title] || 0) || 0);
    });
  }

  async function refreshWizardEligibility() {
    const legendTitle = String(state.wizard.deck.legendTitle || "").trim();
    if (!legendTitle) {
      state.wizard.eligibility = null;
      return null;
    }
    const formatName = String(state.wizard.format || "constructed").trim() || "constructed";
    const payload = await api(
      `/api/decks/eligibility?format=${encodeURIComponent(formatName)}&legendTitle=${encodeURIComponent(legendTitle)}&limit=1000`
    );
    state.wizard.eligibility = payload || null;
    return payload;
  }

  function wizardLegalChampionCards() {
    const rows = Array.isArray(state.wizard.eligibility && state.wizard.eligibility.champions)
      ? state.wizard.eligibility.champions
      : [];
    if (rows.length) {
      return rows
        .map((row) => lookupCard(row.title) || row)
        .filter((card) => card && card.title);
    }
    const tags = wizardLegendChampionTagSet(state.wizard.deck.legendTitle);
    return fallbackChampionCards().filter((card) => {
      if (!tags.size) return true;
      const cardTags = cardChampionTagSet(card);
      for (const tag of tags) {
        if (cardTags.has(tag)) return true;
      }
      return false;
    });
  }

  function wizardChecklistRowHtml(title, requiredQty, options) {
    const opts = options || {};
    const info = lookupCard(title);
    const required = Math.max(0, Number(requiredQty || 0) || 0);
    const assumeFull = Boolean(opts.assumeOwned);
    const ownedQty = assumeFull ? required : getWizardOwnedQty(title, required);
    const missing = assumeFull ? 0 : getWizardMissingCount(title, required);
    const isSelected = canonicalTitle(state.wizard.activeReplacementCard || "") === canonicalTitle(title);
    const isComplete = missing === 0;
    const isPartial = missing > 0 && ownedQty > 0;
    const allowStepper = opts.allowStepper !== false && required > 0 && !assumeFull;
    const image = info && info.imageUrl ? info.imageUrl : cardBackFor(title);
    const statusClass = isComplete ? "is-complete" : isPartial ? "is-partial" : "is-short";
    const statusLabel = `${ownedQty} / ${required} in collection`;

    const stepper = allowStepper
      ? `<div class="qty-stepper wizard-checklist-stepper">` +
        `<button type="button" class="step-btn wizard-owned-dec" data-title="${escAttr(title)}"${ownedQty <= 0 ? " disabled" : ""}>-</button>` +
        `<span class="step-value">${esc(ownedQty)} / ${esc(required)}</span>` +
        `<button type="button" class="step-btn wizard-owned-inc" data-title="${escAttr(title)}"${ownedQty >= required ? " disabled" : ""}>+</button>` +
        `</div>`
      : "";

    const findRepl =
      missing > 0
        ? `<button type="button" class="card-action-btn secondary wizard-find-repl-btn" data-title="${escAttr(title)}">Replacements</button>`
        : "";

    return (
      `<div class="wizard-card-row wizard-checklist-row ${statusClass}${isSelected ? " active" : ""}" data-title="${escAttr(title)}">` +
      `<div class="wizard-checklist-row-main">` +
      `<div class="wizard-checklist-thumb-wrap">` +
      `<img class="wizard-checklist-thumb${info && info.imageUrl ? "" : " is-fallback"}" src="${escAttr(image)}" alt="${escAttr(title)}" data-fallback-src="${escAttr(cardBackFor(title))}" />` +
      `</div>` +
      `<div class="wizard-checklist-copy">` +
      `<div class="wizard-card-row-left">` +
      `<span class="wizard-card-row-qty">${esc(required)}x</span>` +
      `<span class="wizard-card-row-name">${esc(title)}</span>` +
      `</div>` +
      `<span class="wizard-checklist-meta">${esc(info ? cardMetaLine(info) : "Unresolved card")}</span>` +
      `</div>` +
      `</div>` +
      `<div class="wizard-checklist-row-actions">` +
      `<span class="wizard-ownership-pill ${statusClass}">${esc(statusLabel)}</span>` +
      `${stepper}` +
      `${findRepl}` +
      `</div>` +
      `</div>`
    );
  }

  function resetWizard() {
    state.wizard.step = "start";
    state.wizard.format = "constructed";
    state.wizard.collectionAgnostic = false;
    state.wizard.transientCollection = {};
    state.wizard.eligibility = null;
    state.wizard.deck = {
      name: "Guided Deck",
      source: "wizard",
      format: "constructed",
      legendTitle: "",
      chosenChampionTitle: "",
      main: {},
      runes: {},
      battlefields: ["", "", ""],
      sideboard: {}
    };
    state.wizard.targetDeck = null;
    state.wizard.optimalTargetDeck = null;
    state.wizard.recommendations = [];
    state.wizard.activeReplacementCard = null;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementLoading = false;
    state.wizard.activeReplacementNotice = "";
    state.wizard.physicalChecklistMode = false;
    state.wizard.decisions = [];
    state.wizard.searchQuery = "";
    state.wizard.iteration = 0;
    state.wizard.iterationHistory = [];
    state.wizard.savedRecommendations = [];
    state.wizard.lastRefinement = null;
    state.wizard.completeData = null;

    const actions = document.getElementById("wizard-global-actions");
    if (actions) actions.style.display = "none";

    renderWizard();
  }

  function renderWizard(options) {
    const opts = options && typeof options === "object" ? options : {};
    const step = state.wizard.step;
    if (step === "start") {
      renderWizardStart();
    } else if (step === "legend") {
      renderWizardLegend();
    } else if (step === "champion") {
      void loadWizardChampionData();
    } else if (step === "champion-render") {
      renderWizardChampionRender();
    } else if (step === "refining") {
      renderWizardRefining();
    } else if (step === "deckbuilding") {
      renderWizardDeckbuilding(opts);
    } else if (step === "complete") {
      if (!state.wizard.completeData) {
        void loadWizardCompleteData();
      } else {
        renderWizardComplete();
      }
    } else if (step === "complete-render") {
      renderWizardComplete();
    }
  }

  function renderWizardStart() {
    const container = document.getElementById("wizard-container");
    if (!container) return;

    container.innerHTML = `
      <div class="wizard-start-pane">
        <h3>Guided Deck Build</h3>
        <p class="muted wizard-start-copy">
          Walk through legend, champion, and list selection like the manual Build tab — with synergy suggestions when you are short copies of a card.
        </p>
        <div style="margin-bottom: 1.5rem; text-align: left;">
          <label style="display: block; font-weight: bold; margin-bottom: 0.5rem;">Select Format:</label>
          <select id="wizard-format-select" class="form-control" style="width: 100%; padding: 0.75rem; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-gold); border-radius: 4px;">
            <option value="constructed">Constructed</option>
            <option value="skirmish">Skirmish</option>
          </select>
        </div>
        <div style="margin-bottom: 2rem; text-align: left; display: flex; align-items: center; gap: 0.75rem;">
          <input type="checkbox" id="wizard-agnostic-checkbox" style="width: 20px; height: 20px; cursor: pointer;">
          <label for="wizard-agnostic-checkbox" style="font-weight: bold; cursor: pointer; color: var(--text-light); margin: 0; user-select: none;">
            Collection Agnostic (assume full catalog except marked shortages)
          </label>
        </div>
        <button id="wizard-start-begin-btn" type="button" class="primary wizard-start-btn">
          Begin Guided Build
        </button>
      </div>
    `;

    const actions = document.getElementById("wizard-global-actions");
    if (actions) actions.style.display = "none";

    document.getElementById("wizard-start-begin-btn").addEventListener("click", async () => {
      const fmtSelect = document.getElementById("wizard-format-select");
      const fmt = fmtSelect ? fmtSelect.value : "constructed";
      state.wizard.format = fmt;
      state.wizard.deck.format = fmt;

      const agnosticChk = document.getElementById("wizard-agnostic-checkbox");
      const agnostic = agnosticChk ? agnosticChk.checked : false;
      state.wizard.collectionAgnostic = agnostic;

      if (!agnostic) {
        if (!state.collection || Object.keys(state.collection).length === 0) {
          try {
            const payload = await api("/api/collection");
            state.collection = wizardCollectionCardsMap(payload);
          } catch (e) {
            console.warn("Could not load collection, starting fresh:", e);
            state.collection = {};
          }
        }
        state.wizard.transientCollection = wizardCollectionCardsMap(state.collection || {});
      } else {
        state.wizard.transientCollection = {};
      }
      assumeWizardLegendsOwned();
      assumeWizardRunesOwned();

      state.wizard.step = "legend";
      const globalActions = document.getElementById("wizard-global-actions");
      if (globalActions) globalActions.style.display = "block";
      renderWizard();
    });
  }

  function renderWizardLegend() {
    const container = document.getElementById("wizard-container");
    if (!container) return;

    const legends = fallbackLegendCards();
    const query = (state.wizard.searchQuery || "").trim().toLowerCase();
    const filtered = legends.filter(c => c.title.toLowerCase().includes(query));

    let cardsHtml = "";
    if (filtered.length === 0) {
      cardsHtml = `<div class="wizard-grid-empty muted">No legends found matching "${esc(state.wizard.searchQuery)}".</div>`;
    } else {
      filtered.forEach(card => {
        const title = card.title;
        const actions = `<button type="button" class="card-action-btn select-legend-btn" data-title="${escAttr(title)}">Select Legend</button>`;

        cardsHtml += tileHtml({
          title: title,
          imageUrl: card.imageUrl,
          meta: cardMetaLine(card),
          stats: cardStatsLine(card),
          rarity: card.rarity,
          actions: actions,
          extraClass: "wizard-pick-card",
          disablePreview: true
        });
      });
    }

    container.innerHTML = `
      <div class="wizard-step-pane">
        <div class="wizard-step-head">
          <div>
            <h3 class="wizard-step-title">Step 1 — Legend</h3>
            <p class="muted">Pick your legend. All legends are treated as available for this guided build.</p>
          </div>
        </div>
        <div class="wizard-filter-bar">
          <label class="wizard-filter-label" for="wizard-legend-search">Search legends</label>
          <input id="wizard-legend-search" class="wizard-search-input" type="search" autocomplete="off" placeholder="Type a legend name…" value="${escAttr(state.wizard.searchQuery || "")}">
        </div>
        <div class="wizard-grid tile-grid wizard-pick-grid">${cardsHtml}</div>
      </div>
    `;

    bindCardImageFallbacks(container);
    bindFoilInteractions(container);

    const searchInput = document.getElementById("wizard-legend-search");
    if (searchInput) {
      searchInput.addEventListener("input", (ev) => {
        state.wizard.searchQuery = ev.target.value;
        renderWizardLegend();
      });
    }

    container.querySelectorAll(".select-legend-btn").forEach(btn => {
      btn.addEventListener("click", (ev) => {
        const title = btn.getAttribute("data-title");
        setWizardOwnedQty(title, 1);
        state.wizard.deck.legendTitle = title;
        state.wizard.searchQuery = "";
        loadWizardPlaylistFromStorage();
        state.wizard.step = "champion";
        renderWizard();
      });
    });
  }

  async function loadWizardChampionData() {
    const container = document.getElementById("wizard-container");
    if (!container) return;
    container.innerHTML = `
      <div style="text-align: center; padding: 5rem 0;">
        <div class="loader" style="margin: 0 auto 1.5rem auto; border: 4px solid var(--bg-card); border-top: 4px solid var(--text-gold); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite;"></div>
        <h4 style="color: var(--text-gold);">Finding Synergistic Champions...</h4>
        <p class="muted">Querying machine learning models for top synergy with ${esc(state.wizard.deck.legendTitle)}...</p>
      </div>
    `;

    try {
      await refreshWizardEligibility();
      const response = await api("/api/auto-builder/recommendations", {
        method: "POST",
        body: {
          top: 24,
          rankingMode: "collection",
          strategyMode: "hybrid",
          legendTitle: state.wizard.deck.legendTitle,
          collectionOverride: state.wizard.transientCollection
        }
      });

      state.wizard.recommendations = Array.isArray(response.recommendations) ? response.recommendations : [];
      state.wizard.step = "champion-render";
      renderWizard();
    } catch (err) {
      console.error("Error fetching recommendations:", err);
      state.wizard.recommendations = [];
      state.wizard.step = "champion-render";
      renderWizard();
    }
  }

  function renderWizardChampionRender() {
    const container = document.getElementById("wizard-container");
    if (!container) return;

    const suggestedChampionMap = {};
    state.wizard.recommendations.forEach((rec) => {
      const champ = rec.deck && rec.deck.chosenChampionTitle;
      if (champ) {
        if (!suggestedChampionMap[champ]) {
          suggestedChampionMap[champ] = {
            title: champ,
            count: 0,
            bestScore: 0,
            card: lookupCard(champ)
          };
        }
        suggestedChampionMap[champ].count++;
        suggestedChampionMap[champ].bestScore = Math.max(suggestedChampionMap[champ].bestScore, rec.competitiveScore || 0);
      }
    });

    const legalTitles = new Set(wizardLegalChampionCards().map((c) => canonicalTitle(c.title)));
    const suggestedChampions = Object.values(suggestedChampionMap)
      .filter((item) => legalTitles.has(canonicalTitle(item.title)))
      .sort((a, b) => b.count - a.count || b.bestScore - a.bestScore);
    const suggestedTitles = new Set(suggestedChampions.map((c) => canonicalTitle(c.title)));

    const otherChampions = wizardLegalChampionCards().filter((c) => !suggestedTitles.has(canonicalTitle(c.title)));

    const query = (state.wizard.searchQuery || "").trim().toLowerCase();

    const filterFn = c => c.title.toLowerCase().includes(query);
    const filteredSuggested = suggestedChampions.filter(c => c.title.toLowerCase().includes(query));
    const filteredOthers = otherChampions.filter(filterFn);

    let suggestedHtml = "";
    if (filteredSuggested.length > 0) {
      filteredSuggested.forEach(item => {
        const title = item.title;
        const card = item.card || lookupCard(title);
        const actions = `<button type="button" class="card-action-btn select-champion-btn" data-title="${escAttr(title)}">Select Champion</button>`;

        suggestedHtml += tileHtml({
          title: title,
          imageUrl: card ? card.imageUrl : "",
          meta: card ? cardMetaLine(card) : "",
          stats: card ? cardStatsLine(card) : "",
          rarity: card ? card.rarity : "",
          badge: "Synergistic",
          badgeClass: "badge-gold",
          actions: actions,
          extraClass: "wizard-pick-card",
          disablePreview: true
        });
      });
    }

    let othersHtml = "";
    if (filteredOthers.length > 0) {
      filteredOthers.forEach(card => {
        const title = card.title;
        const actions = `<button type="button" class="card-action-btn select-champion-btn" data-title="${escAttr(title)}">Select Champion</button>`;

        othersHtml += tileHtml({
          title: title,
          imageUrl: card.imageUrl,
          meta: cardMetaLine(card),
          stats: cardStatsLine(card),
          rarity: card.rarity,
          actions: actions,
          extraClass: "wizard-pick-card",
          disablePreview: true
        });
      });
    }

    container.innerHTML = `
      <div class="wizard-step-pane">
        <div class="wizard-step-head">
          <div>
            <h3 class="wizard-step-title">Step 2 — Chosen Champion</h3>
            <p class="muted">Only champions legal for ${esc(state.wizard.deck.legendTitle || "this legend")} are listed. ML suggestions appear first.</p>
          </div>
        </div>
        <div class="wizard-filter-bar">
          <label class="wizard-filter-label" for="wizard-champion-search">Search champions</label>
          <input id="wizard-champion-search" class="wizard-search-input" type="search" autocomplete="off" placeholder="Type a champion name…" value="${escAttr(state.wizard.searchQuery || "")}">
        </div>

        ${filteredSuggested.length > 0 ? `
          <div class="wizard-champion-section">
            <h4 class="wizard-deck-group-title">Suggested Champions</h4>
            <div class="wizard-grid tile-grid wizard-pick-grid">${suggestedHtml}</div>
          </div>
        ` : ""}

        <div class="wizard-champion-section">
          <h4 class="wizard-deck-group-title">Legal Champions</h4>
          <div class="wizard-grid tile-grid wizard-pick-grid">
            ${othersHtml || `<div class="wizard-grid-empty muted">No other legal champions match "${esc(state.wizard.searchQuery)}".</div>`}
          </div>
        </div>
      </div>
    `;

    bindCardImageFallbacks(container);
    bindFoilInteractions(container);

    const searchInput = document.getElementById("wizard-champion-search");
    if (searchInput) {
      searchInput.addEventListener("input", (ev) => {
        state.wizard.searchQuery = ev.target.value;
        renderWizardChampionRender();
      });
    }

    container.querySelectorAll(".select-champion-btn").forEach(btn => {
      btn.addEventListener("click", (ev) => {
        const title = btn.getAttribute("data-title");
        setWizardOwnedQty(title, 1);
        state.wizard.deck.chosenChampionTitle = title;

        let template = null;
        const match = state.wizard.recommendations.find(rec => rec.deck && rec.deck.chosenChampionTitle === title);
        if (match) {
          template = match.deck;
        }

        if (template) {
          state.wizard.deck = JSON.parse(JSON.stringify(template));
          state.wizard.targetDeck = JSON.parse(JSON.stringify(template));
          state.wizard.optimalTargetDeck = JSON.parse(JSON.stringify(template));
          beginWizardDeckbuildingIteration();
          loadWizardPlaylistFromStorage();
          state.wizard.step = "deckbuilding";
          state.wizard.searchQuery = "";
          renderWizard();
        } else {
          void withBusy(btn, "Loading template...", async () => {
            try {
              const resp = await api("/api/auto-builder/recommendations", {
                method: "POST",
                body: {
                  top: 3,
                  rankingMode: "collection",
                  strategyMode: "hybrid",
                  legendTitle: state.wizard.deck.legendTitle,
                  chosenChampionTitle: title,
                  collectionOverride: state.wizard.transientCollection
                }
              });
              const recs = Array.isArray(resp.recommendations) ? resp.recommendations : [];
              const found = recs.find(rec => rec.deck);
              if (found) {
                state.wizard.deck = JSON.parse(JSON.stringify(found.deck));
                state.wizard.targetDeck = JSON.parse(JSON.stringify(found.deck));
                state.wizard.optimalTargetDeck = JSON.parse(JSON.stringify(found.deck));
              } else {
                state.wizard.deck.chosenChampionTitle = title;
                try {
                  const solveResp = await api("/api/wizard/solve", {
                    method: "POST",
                    body: {
                      legendTitle: state.wizard.deck.legendTitle,
                      chosenChampionTitle: title,
                      format: state.wizard.format || "constructed",
                      owned: state.wizard.collectionAgnostic ? {} : state.wizard.transientCollection,
                      referenceDeck: null,
                      currentDeck: state.wizard.deck,
                      mode: "owned_only",
                      maxIterations: 1,
                      collectionAgnostic: state.wizard.collectionAgnostic || false
                    }
                  });
                  if (solveResp && solveResp.deck) {
                    state.wizard.deck = capWizardDeckMainCopies(solveResp.deck);
                  }
                } catch (solveErr) {
                  console.error("Failed to solve initial empty deck:", solveErr);
                }
                state.wizard.targetDeck = JSON.parse(JSON.stringify(state.wizard.deck));
                state.wizard.optimalTargetDeck = JSON.parse(JSON.stringify(state.wizard.deck));
              }
              beginWizardDeckbuildingIteration();
              loadWizardPlaylistFromStorage();
              state.wizard.step = "deckbuilding";
              state.wizard.searchQuery = "";
              renderWizard();
            } catch (e) {
              console.error("Failed to load champion template:", e);
              setStatus("Could not load deck template for this champion.", true);
            }
          });
        }
      });
    });
  }

  function renderWizardDeckbuilding(options) {
    const opts = options || {};
    const container = document.getElementById("wizard-container");
    if (!container) return;

    const scrollEl = container.querySelector(".wizard-checklist-groups");
    const savedScroll = opts.preserveChecklistScroll && scrollEl ? scrollEl.scrollTop : null;

    seedWizardTransientFromDeck();
    state.wizard.deck = capWizardDeckMainCopies(state.wizard.deck);
    const deck = state.wizard.deck;

    const appendGroup = (rows, label) => {
      if (!rows.length) return "";
      return `<div class="wizard-checklist-group"><h4 class="wizard-deck-group-title">${esc(label)}</h4>${rows.join("")}</div>`;
    };

    let checklistHtml = "";

    if (deck.legendTitle) {
      checklistHtml += appendGroup([wizardChecklistRowHtml(deck.legendTitle, 1, { allowStepper: false })], "Legend");
    }

    if (deck.chosenChampionTitle) {
      checklistHtml += appendGroup([wizardChecklistRowHtml(deck.chosenChampionTitle, 1)], "Chosen Champion");
    }

    const runes = deck.runes || {};
    const runesKeys = Object.keys(runes).filter(Boolean).sort((a, b) => compareTitlesByCatalogOrder(a, b));
    if (runesKeys.length > 0) {
      checklistHtml += appendGroup(
        runesKeys.map((title) => wizardChecklistRowHtml(title, runes[title], { allowStepper: false, assumeOwned: true })),
        "Runes"
      );
    }

    const battlefieldCounts = {};
    (deck.battlefields || []).forEach((title) => {
      if (title) battlefieldCounts[title] = (battlefieldCounts[title] || 0) + 1;
    });
    const bfKeys = Object.keys(battlefieldCounts).sort((a, b) => compareTitlesByCatalogOrder(a, b));
    if (bfKeys.length > 0) {
      checklistHtml += appendGroup(bfKeys.map((title) => wizardChecklistRowHtml(title, battlefieldCounts[title])), "Battlefields");
    }

    const main = deck.main || {};
    const mainKeys = Object.keys(main)
      .filter((title) => {
        const key = canonicalTitle(title);
        return key && key !== canonicalTitle(deck.legendTitle) && key !== canonicalTitle(deck.chosenChampionTitle);
      })
      .sort((a, b) => compareTitlesByCatalogOrder(a, b));
    if (mainKeys.length > 0) {
      checklistHtml += appendGroup(mainKeys.map((title) => wizardChecklistRowHtml(title, main[title])), "Main Deck");
    }

    const sideboard = deck.sideboard || {};
    const sbKeys = Object.keys(sideboard).filter(Boolean).sort((a, b) => compareTitlesByCatalogOrder(a, b));
    if (sbKeys.length > 0) {
      checklistHtml += appendGroup(sbKeys.map((title) => wizardChecklistRowHtml(title, sideboard[title])), "Sideboard");
    }

    let replacementsHtml = "";
    if (state.wizard.activeReplacementLoading) {
      replacementsHtml = `
        <div style="text-align: center; padding: 2rem 0;">
          <div class="loader" style="margin: 0 auto 1rem auto; border: 3px solid var(--bg-card); border-top: 3px solid var(--text-gold); border-radius: 50%; width: 24px; height: 24px; animation: spin 1s linear infinite;"></div>
          <p class="muted" style="font-size: 0.9rem;">Analyzing replacement candidates...</p>
        </div>
      `;
    } else if (!state.wizard.activeReplacementOptions || state.wizard.activeReplacementOptions.length === 0) {
      const notice = state.wizard.activeReplacementNotice || "No legal owned-card replacements found for this card.";
      replacementsHtml = `<div class="muted" style="padding: 1rem 0; text-align: center;">${esc(notice)}</div>`;
    } else {
      state.wizard.activeReplacementOptions.slice(0, 5).forEach((opt, optionIndex) => {
        if (opt && opt.cluster) {
          const addedRows = (opt.added || []).map((row) => `${row.qty || 0}x ${row.card || ""}`).filter(Boolean).join(", ");
          const removedRows = (opt.removed || []).map((row) => `${row.qty || 0}x ${row.card || ""}`).filter(Boolean).join(", ");
          const matchScore = opt.score ? `${Math.round(opt.score * 100)}% owned` : "";
          const reason = opt.reason ? String(opt.reason) : "Legal owned-card replacement cluster";
          replacementsHtml += `
            <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 0.75rem; border-radius: 4px; margin-bottom: 0.75rem; display: flex; flex-direction: column; gap: 0.5rem;">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;">
                <span style="font-weight: bold; color: var(--text-gold);">Replacement cluster</span>
                <span style="font-size: 0.8rem; background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); padding: 0.1rem 0.3rem; border-radius: 3px;">Legal</span>
              </div>
              <div style="font-size: 0.8rem; display: flex; align-items: center; gap: 0.5rem; justify-content: space-between;">
                <span style="color: var(--text-gold); font-weight: 500;">${esc(matchScore)}</span>
                <span class="muted" style="font-size: 0.75rem;">Source: ${esc(opt.source || "owned-solver")}</span>
              </div>
              <div style="font-size: 0.8rem; line-height: 1.35;" class="muted">${esc(reason)}</div>
              ${removedRows ? `<div style="font-size: 0.78rem;" class="muted">Out: ${esc(removedRows)}</div>` : ""}
              ${addedRows ? `<div style="font-size: 0.78rem;">In: ${esc(addedRows)}</div>` : ""}
              <button type="button" class="wizard-apply-cluster-btn primary" data-cluster-index="${escAttr(optionIndex)}" style="padding: 0.35rem; font-size: 0.8rem; width: 100%;">
                Apply Cluster
              </button>
            </div>
          `;
          return;
        }
        const title = opt.card;
        const info = lookupCard(title);
        const owned = getWizardOwnedQty(title);
        const hasIt = owned > 0;
        const matchScore = opt.score ? `${Math.round(opt.score * 100)}% match` : "";
        const reason = opt.reason ? String(opt.reason) : "";

        const previewAttrs = info ? `
          data-preview-title="${escAttr(title)}"
          data-preview-image="${escAttr(info.imageUrl || "")}"
          data-preview-meta="${escAttr(cardMetaLine(info))}"
          data-preview-stats="${escAttr(cardStatsLine(info))}"
          data-preview-fallback="${escAttr(initials(title))}"
        ` : "";

        replacementsHtml += `
          <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 0.75rem; border-radius: 4px; margin-bottom: 0.75rem; display: flex; flex-direction: column; gap: 0.5rem;">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;">
              <span class="wizard-card-link" ${previewAttrs} style="font-weight: bold; text-decoration: underline; cursor: help; color: var(--text-gold);">${esc(title)}</span>
              <span style="font-size: 0.8rem; background: ${hasIt ? 'rgba(74, 222, 128, 0.15)' : 'rgba(234, 179, 8, 0.15)'}; color: ${hasIt ? '#4ade80' : '#eab308'}; border: 1px solid ${hasIt ? 'rgba(74, 222, 128, 0.3)' : 'rgba(234, 179, 8, 0.3)'}; padding: 0.1rem 0.3rem; border-radius: 3px;">
                ${hasIt ? 'Owned' : 'Need'}
              </span>
            </div>
            <div style="font-size: 0.8rem; display: flex; align-items: center; gap: 0.5rem; justify-content: space-between;">
              <span style="color: var(--text-gold); font-weight: 500;">${esc(matchScore)}</span>
              <span class="muted" style="font-size: 0.75rem;">Source: ${esc(opt.source || 'hybrid')}</span>
            </div>
            ${reason ? `<div style="font-size: 0.8rem; line-height: 1.3;" class="muted">${esc(reason)}</div>` : ""}
            <button type="button" class="wizard-swap-btn primary" data-original="${escAttr(state.wizard.activeReplacementCard)}" data-replace="${escAttr(title)}" style="padding: 0.35rem; font-size: 0.8rem; width: 100%;">
              Swap Card 🪄
            </button>
          </div>
        `;
      });
    }

    const finalizeReady = canFinalizeWizard();
    const mainInventory = wizardMainInventoryMetrics();
    const mainInventoryPct = Math.round(mainInventory.completionPct);
    const physicalMode = Boolean(state.wizard.physicalChecklistMode);
    let inspectorHtml = "";
    if (!state.wizard.activeReplacementCard) {
      inspectorHtml = `
        <div class="wizard-inspector-empty wizard-inspector-refine">
          <div class="wizard-inspector-empty-icon">◇</div>
          <h4>Iterative build</h4>
          <p class="muted">
            Mark what you own, then refine. The model rebuilds toward the strongest legal deck your collection can support and saves upgrade ideas for later.
          </p>
          <div class="wizard-inspector-actions">
            <button id="wizard-refine-deck-btn" type="button" class="card-action-btn primary">Refine for my collection</button>
            ${finalizeReady ? `<button id="wizard-finalize-deck-btn" type="button" class="card-action-btn">Finalize strongest deck</button>` : ""}
          </div>
          <div class="wizard-playlist-panel">
            <h4 class="wizard-playlist-title">Saved upgrade ideas</h4>
            ${wizardPlaylistPanelHtml()}
          </div>
        </div>
      `;
    } else {
      const activeCard = state.wizard.activeReplacementCard;
      const info = lookupCard(activeCard);
      const activeCardMeta = info ? cardMetaLine(info) : "Unknown Card Type";
      const activeCardEffect = info ? info.effect || "No effect text." : "No description available.";

      inspectorHtml = `
        <div class="wizard-active-inspector">
          <div class="wizard-inspector-title-row">
            <h4 class="wizard-inspector-name">Replacements</h4>
            <button id="wizard-clear-inspector-btn" type="button" class="card-action-btn secondary">Close</button>
          </div>
          <div class="wizard-inspector-card-detail">
            <div class="wizard-inspector-name">${esc(activeCard)}</div>
            <div class="wizard-inspector-meta">${esc(activeCardMeta)}</div>
            <p class="wizard-inspector-text">${esc(activeCardEffect)}</p>
          </div>
          <div class="wizard-replacements-section">
            <h4>Synergistic options</h4>
            <div class="wizard-replacements-list">${replacementsHtml}</div>
          </div>
        </div>
      `;
    }

    container.innerHTML = `
      <div class="wizard-workspace-layout wizard-deckbuilding-layout">
        <div class="wizard-deck-column wizard-deck-checklist">
          <div class="worktable-row-head">
            <h3>Guided Deck Checklist</h3>
          </div>
          ${wizardIterationBannerHtml()}
          <div class="wizard-checklist-toolbar">
            <div class="wizard-checklist-progress">
              <span class="wizard-checklist-progress-label">Main deck found</span>
              <strong>${esc(mainInventory.owned)} / ${esc(mainInventory.required)}</strong>
              <span class="wizard-checklist-progress-pct">${esc(mainInventoryPct)}%</span>
            </div>
            <label class="wizard-physical-toggle">
              <input id="wizard-physical-check-toggle" type="checkbox"${physicalMode ? " checked" : ""}>
              <span class="wizard-physical-toggle-ui" aria-hidden="true"></span>
              <span class="wizard-physical-toggle-copy">
                <strong>Physical check</strong>
                <small>Set main deck to zero, then add cards as you find them.</small>
              </span>
            </label>
          </div>
          <div class="wizard-checklist-groups">${checklistHtml}</div>
        </div>
        <div class="wizard-help-column wizard-inspector-panel">${inspectorHtml}</div>
      </div>
    `;

    bindPreviewInteractions(container);
    bindCardImageFallbacks(container);

    if (savedScroll !== null) {
      requestAnimationFrame(() => {
        const el = container.querySelector(".wizard-checklist-groups");
        if (el) el.scrollTop = savedScroll;
      });
    }

    const physicalToggle = document.getElementById("wizard-physical-check-toggle");
    if (physicalToggle) {
      physicalToggle.addEventListener("change", () => {
        const enabled = Boolean(physicalToggle.checked);
        state.wizard.physicalChecklistMode = enabled;
        applyWizardPhysicalChecklistMode(enabled);
        state.wizard.activeReplacementCard = null;
        state.wizard.activeReplacementOptions = [];
        state.wizard.activeReplacementNotice = "";
        renderWizardPreservingChecklistScroll();
        setStatus(enabled ? "Main deck marked missing for physical checking." : "Main deck ownership restored.", false);
      });
    }

    const requiredQtyForTitle = (title) => {
      const key = canonicalTitle(title);
      const d = state.wizard.deck;
      if (key === canonicalTitle(d.legendTitle)) return 1;
      if (key === canonicalTitle(d.chosenChampionTitle)) return 1;
      if (d.main && d.main[title] !== undefined) return Math.max(0, Number(d.main[title] || 0) || 0);
      if (d.runes && d.runes[title] !== undefined) return Math.max(0, Number(d.runes[title] || 0) || 0);
      if (d.sideboard && d.sideboard[title] !== undefined) return Math.max(0, Number(d.sideboard[title] || 0) || 0);
      let bfCount = 0;
      (d.battlefields || []).forEach((bf) => {
        if (canonicalTitle(bf) === key) bfCount += 1;
      });
      return bfCount;
    };

    container.querySelectorAll(".wizard-owned-inc").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const title = btn.getAttribute("data-title");
        const required = requiredQtyForTitle(title);
        const next = Math.min(required, getWizardOwnedQty(title, required) + 1);
        setWizardOwnedQty(title, next);
        if (getWizardMissingCount(title, required) > 0 && !state.wizard.activeReplacementCard) {
          void selectWizardCardForInspector(title);
        } else {
          renderWizardPreservingChecklistScroll();
        }
      });
    });

    container.querySelectorAll(".wizard-owned-dec").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const title = btn.getAttribute("data-title");
        const required = requiredQtyForTitle(title);
        const next = Math.max(0, getWizardOwnedQty(title, required) - 1);
        setWizardOwnedQty(title, next);
        if (getWizardMissingCount(title, required) > 0) {
          void selectWizardCardForInspector(title);
        } else if (canonicalTitle(state.wizard.activeReplacementCard || "") === canonicalTitle(title)) {
          state.wizard.activeReplacementCard = null;
          state.wizard.activeReplacementOptions = [];
          state.wizard.activeReplacementNotice = "";
          renderWizardPreservingChecklistScroll();
        } else {
          renderWizardPreservingChecklistScroll();
        }
      });
    });

    container.querySelectorAll(".wizard-find-repl-btn").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        void selectWizardCardForInspector(btn.getAttribute("data-title"));
      });
    });

    container.querySelectorAll(".wizard-checklist-row").forEach((row) => {
      row.addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        const title = row.getAttribute("data-title");
        const required = requiredQtyForTitle(title);
        if (getWizardMissingCount(title, required) > 0) {
          void selectWizardCardForInspector(title);
        }
      });
    });

    const clearBtn = document.getElementById("wizard-clear-inspector-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        state.wizard.activeReplacementCard = null;
        state.wizard.activeReplacementOptions = [];
        state.wizard.activeReplacementNotice = "";
        renderWizardPreservingChecklistScroll();
      });
    }

    container.querySelectorAll(".wizard-swap-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const original = btn.getAttribute("data-original");
        const replace = btn.getAttribute("data-replace");
        void performWizardSwap(original, replace);
      });
    });

    container.querySelectorAll(".wizard-apply-cluster-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const index = Math.max(0, Number(btn.getAttribute("data-cluster-index") || 0) || 0);
        void performWizardClusterApply(index);
      });
    });

    const refineBtn = document.getElementById("wizard-refine-deck-btn");
    if (refineBtn) {
      refineBtn.addEventListener("click", () => {
        void withBusy(refineBtn, "Refining...", () => runWizardRefinement());
      });
    }

    const finalizeBtn = document.getElementById("wizard-finalize-deck-btn");
    if (finalizeBtn) {
      finalizeBtn.addEventListener("click", () => {
        void finalizeWizardDeck();
      });
    }
  }

  function seedWizardTransientFromDeck() {
    const deck = state.wizard.deck;
    const seed = (title, required) => {
      const clean = canonicalTitle(title);
      if (!clean || required <= 0) return;
      if (state.wizard.transientCollection[clean] !== undefined) return;
      if (!state.wizard.collectionAgnostic && state.collection && state.collection[clean] !== undefined) {
        state.wizard.transientCollection[clean] = Math.max(0, Number(state.collection[clean] || 0) || 0);
      } else if (state.wizard.collectionAgnostic) {
        state.wizard.transientCollection[clean] = Math.max(0, Number(required || 0) || 0);
      } else {
        state.wizard.transientCollection[clean] = 0;
      }
    };
    seed(deck.legendTitle, 1);
    seed(deck.chosenChampionTitle, 1);
    Object.entries(deck.main || {}).forEach(([title, qty]) => seed(title, qty));
    Object.entries(deck.runes || {}).forEach(([title, qty]) => {
      const clean = canonicalTitle(title);
      if (!clean || qty <= 0) return;
      const required = Math.max(0, Number(qty || 0) || 0);
      state.wizard.transientCollection[clean] = Math.max(
        required,
        Number(state.wizard.transientCollection[clean] || 0) || 0,
        12
      );
    });
    Object.entries(deck.sideboard || {}).forEach(([title, qty]) => seed(title, qty));
    const bfCounts = {};
    (deck.battlefields || []).forEach((title) => {
      if (!title) return;
      bfCounts[title] = (bfCounts[title] || 0) + 1;
    });
    Object.entries(bfCounts).forEach(([title, qty]) => seed(title, qty));
  }

  async function selectWizardCardForInspector(cardTitle) {
    state.wizard.activeReplacementCard = cardTitle;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementLoading = true;
    state.wizard.activeReplacementNotice = "";
    renderWizardPreservingChecklistScroll();

    try {
      const tempCollection = wizardEffectiveCollection();
      tempCollection[canonicalTitle(cardTitle)] = getWizardOwnedQty(cardTitle);

      const deck = capWizardDeckMainCopies(state.wizard.deck);
      const legend = String(deck.legendTitle || "").trim();
      const champion = String(deck.chosenChampionTitle || "").trim();
      const [completeResult, solveResult] = await Promise.allSettled([
        api("/api/auto-builder/complete", {
          method: "POST",
          body: {
            deck,
            rankingMode: "collection",
            strategyMode: "hybrid",
            collectionOverride: tempCollection
          }
        }),
        api("/api/wizard/solve", {
          method: "POST",
          body: {
            legendTitle: legend,
            chosenChampionTitle: champion,
            format: state.wizard.format || deck.format || "constructed",
            owned: tempCollection,
            referenceDeck: state.wizard.optimalTargetDeck || state.wizard.targetDeck || deck,
            currentDeck: deck,
            mode: "owned_only",
            maxIterations: 1,
            collectionAgnostic: state.wizard.collectionAgnostic || false
          }
        })
      ]);

      const response = completeResult.status === "fulfilled" ? completeResult.value : {};
      if (completeResult.status === "rejected") {
        console.warn("Single-card replacement plan failed:", completeResult.reason);
      }

      const plan = Array.isArray(response.replacementPlan) ? response.replacementPlan : [];
      const match = plan.find(p => canonicalTitle(p.card) === canonicalTitle(cardTitle));
      const options = match && Array.isArray(match.options) ? match.options : [];
      const validOptions = await Promise.all(options.slice(0, 8).map(async (opt) => {
        const replacement = canonicalTitle(opt && opt.card);
        if (!replacement) return null;
        const original = canonicalTitle(cardTitle);
        const qty = Math.max(0, Number((state.wizard.deck.main || {})[original] || 0) || 0);
        if (qty > 0) {
          const afterQty = Math.min(qty, getWizardOwnedQty(replacement, qty), wizardMainCopyCapForTitle(replacement));
          if (afterQty < qty) return null;
        }
        const candidate = buildWizardSwapCandidate(original, replacement);
        const validation = await validateWizardDeckPayload(candidate);
        return validation && validation.is_valid ? opt : null;
      }));

      const solveResponse = solveResult.status === "fulfilled" ? solveResult.value : null;
      if (solveResult.status === "rejected") {
        console.warn("Owned-card replacement cluster failed:", solveResult.reason);
      }
      const cardKey = canonicalTitle(cardTitle);
      const clusters = solveResponse && Array.isArray(solveResponse.replacementClusters)
        ? solveResponse.replacementClusters
        : [];
      const clusterOptions = clusters
        .filter((cluster) => {
          if (!cluster || cluster.legal === false || !solveResponse.deck) return false;
          return (cluster.removed || []).some((row) => canonicalTitle(row && row.card) === cardKey);
        })
        .map((cluster) => ({
          cluster: true,
          card: "Replacement cluster",
          source: cluster.source || "owned-solver",
          reason: cluster.reason || "Legal owned-card replacement cluster",
          score: Number(cluster.score || ((solveResponse.metrics && solveResponse.metrics.completionPct) || 0) / 100) || 0,
          removed: cluster.removed || [],
          added: cluster.added || [],
          diff: cluster.diff || solveResponse.diff || null,
          deck: solveResponse.deck,
          validation: solveResponse.validation || null,
          solverStatus: solveResponse.solverStatus || ""
        }));

      state.wizard.activeReplacementOptions = validOptions.filter(Boolean).concat(clusterOptions);
      if (!state.wizard.activeReplacementOptions.length) {
        const status = solveResponse && String(solveResponse.solverStatus || "").trim();
        state.wizard.activeReplacementNotice = status === "infeasible_owned_only"
          ? "No legal owned-card cluster is available from the collection data the wizard has. Add owned cards to your collection or save the missing cards as upgrade ideas."
          : "No legal single-card or owned-card cluster replacement found for this card.";
      }
    } catch (e) {
      console.error("Failed to load replacements:", e);
      state.wizard.activeReplacementOptions = [];
      state.wizard.activeReplacementNotice = "Could not load legal replacements for this card.";
    } finally {
      state.wizard.activeReplacementLoading = false;
      renderWizardPreservingChecklistScroll();
    }
  }

  async function performWizardSwap(originalCard, replacementCard) {
    const candidate = buildWizardSwapCandidate(originalCard, replacementCard);
    const validation = await validateWizardDeckPayload(candidate);
    if (!validation || !validation.is_valid) {
      const firstIssue = validation && Array.isArray(validation.issues) && validation.issues[0]
        ? validation.issues[0].code
        : "VALIDATION";
      setStatus(`Swap blocked: ${firstIssue}.`, true);
      state.wizard.lastRefinement = {
        ...(state.wizard.lastRefinement || {}),
        validation,
        message: `Swap blocked because it would make the deck illegal (${firstIssue}).`
      };
      renderWizardPreservingChecklistScroll();
      return;
    }

    state.wizard.deck = candidate;
    state.wizard.decisions.push({
      original: canonicalTitle(originalCard),
      replacedWith: canonicalTitle(replacementCard)
    });
    state.wizard.lastRefinement = {
      ...(state.wizard.lastRefinement || {}),
      validation,
      diff: null,
      message: `Swapped "${canonicalTitle(originalCard)}" with "${canonicalTitle(replacementCard)}" and kept the deck legal.`
    };
    state.wizard.activeReplacementCard = null;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementNotice = "";

    renderWizardPreservingChecklistScroll();
    setStatus(`Swapped "${canonicalTitle(originalCard)}" with "${canonicalTitle(replacementCard)}".`, false);
  }

  async function performWizardClusterApply(optionIndex) {
    const option = (state.wizard.activeReplacementOptions || [])[optionIndex];
    if (!option || !option.cluster || !option.deck) {
      setStatus("Replacement cluster is no longer available.", true);
      return;
    }

    const candidate = capWizardDeckMainCopies(option.deck);
    candidate.name = state.wizard.deck.name || candidate.name;
    candidate.source = "wizard";
    candidate.format = state.wizard.format || candidate.format || "constructed";
    const validation = await validateWizardDeckPayload(candidate);
    if (!validation || !validation.is_valid) {
      const firstIssue = validation && Array.isArray(validation.issues) && validation.issues[0]
        ? validation.issues[0].code
        : "VALIDATION";
      setStatus(`Replacement cluster blocked: ${firstIssue}.`, true);
      state.wizard.lastRefinement = {
        ...(state.wizard.lastRefinement || {}),
        validation,
        message: `Replacement cluster blocked because it would make the deck illegal (${firstIssue}).`
      };
      renderWizardPreservingChecklistScroll();
      return;
    }

    const beforeMetrics = wizardDeckBuildMetrics(state.wizard.deck);
    state.wizard.deck = candidate;
    const afterMetrics = wizardDeckBuildMetrics(candidate);
    state.wizard.iteration = wizardNextIterationNumber();
    state.wizard.decisions.push({
      original: canonicalTitle(state.wizard.activeReplacementCard || ""),
      replacementCluster: (option.added || []).map((row) => ({ card: canonicalTitle(row.card), qty: Math.max(0, Number(row.qty || 0) || 0) }))
    });
    state.wizard.lastRefinement = {
      ...(state.wizard.lastRefinement || {}),
      deckChanged: true,
      buildablePct: afterMetrics.completionPct,
      isBuildable: afterMetrics.isBuildable,
      solverStatus: option.solverStatus || "feasible",
      validation,
      diff: option.diff || null,
      replacementClusters: [option],
      message: `Applied a legal owned-card replacement cluster at ${Math.round(afterMetrics.completionPct)}% collection match.`
    };
    state.wizard.iterationHistory.push({
      iteration: state.wizard.iteration,
      beforeCompletionPct: beforeMetrics.completionPct,
      afterCompletionPct: afterMetrics.completionPct,
      deckChanged: true,
      isBuildable: afterMetrics.isBuildable,
      solverStatus: option.solverStatus || "feasible"
    });
    state.wizard.activeReplacementCard = null;
    state.wizard.activeReplacementOptions = [];
    state.wizard.activeReplacementNotice = "";

    renderWizardPreservingChecklistScroll();
    setStatus(state.wizard.lastRefinement.message, false);
  }

  function performWizardSwapLegacy(originalCard, replacementCard) {
    void performWizardSwap(originalCard, replacementCard);
  }

  async function loadWizardCompleteData() {
    const container = document.getElementById("wizard-container");
    if (!container) return;
    container.innerHTML = `
      <div style="text-align: center; padding: 5rem 0;">
        <div class="loader" style="margin: 0 auto 1.5rem auto; border: 4px solid var(--bg-card); border-top: 4px solid var(--text-gold); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite;"></div>
        <h4 style="color: var(--text-gold);">Wrapping up your strongest build...</h4>
        <p class="muted">Scoring your deck and preparing save options.</p>
      </div>
    `;

    try {
      const currentAnalysis = await api("/api/decks/analyze", {
        method: "POST",
        body: {
          deck: state.wizard.deck,
          collectionOverride: state.wizard.transientCollection
        }
      });

      const completeRes = await api("/api/auto-builder/complete", {
        method: "POST",
        body: {
          deck: state.wizard.deck,
          rankingMode: "collection",
          strategyMode: "hybrid",
          collectionOverride: state.wizard.transientCollection
        }
      });

      let targetScore = 0.85;
      if (state.wizard.targetDeck) {
        const match = state.wizard.recommendations.find(rec => rec.deck && rec.deck.chosenChampionTitle === state.wizard.targetDeck.chosenChampionTitle);
        if (match) {
          targetScore = match.competitiveScore || 0.85;
        }
      }

      const currentScore = (completeRes.bestCandidate && completeRes.bestCandidate.competitiveScore) || targetScore - 0.1;

      const buildMetrics = wizardDeckBuildMetrics(state.wizard.deck);
      state.wizard.completeData = {
        analysis: currentAnalysis.analysis || {},
        targetScore: targetScore,
        currentScore: currentScore,
        iteration: state.wizard.iteration,
        iterationHistory: state.wizard.iterationHistory || [],
        buildMetrics,
        playlist: state.wizard.savedRecommendations || []
      };

      state.wizard.step = "complete-render";
      renderWizard();
    } catch (err) {
      console.error("Error loading complete step data:", err);
      setStatus("Could not load acquisition details.", true);
      state.wizard.completeData = {
        analysis: {},
        targetScore: 0.85,
        currentScore: 0.80
      };
      state.wizard.step = "complete-render";
      renderWizard();
    }
  }

  function renderWizardComplete() {
    const container = document.getElementById("wizard-container");
    if (!container) return;

    const data = state.wizard.completeData;
    const analysis = data.analysis || {};
    const missing = analysis.missing_cards || [];
    const estCost = analysis.estimated_completion_cost;
    const currentScore = data.currentScore || 0.8;
    const targetScore = data.targetScore || 0.85;
    const buildMetrics = data.buildMetrics || wizardDeckBuildMetrics(state.wizard.deck);
    const passCount = Array.isArray(data.iterationHistory) ? data.iterationHistory.length : Math.max(0, wizardVisibleIteration() - 1);

    let iterationSummaryHtml = `
      <div class="wizard-complete-summary">
        <h4>Build summary</h4>
        <p class="muted">Completed after <strong>${esc(String(passCount))}</strong> refinement pass${passCount === 1 ? "" : "es"} for <strong>${esc(state.wizard.deck.legendTitle || "your legend")}</strong>.</p>
        <p><span class="wizard-iteration-pct${buildMetrics.isBuildable ? " is-complete" : ""}">${Math.round(buildMetrics.completionPct)}% collection match</span>${buildMetrics.isBuildable ? " · fully buildable from owned cards" : ""}</p>
      </div>
    `;

    let playlistHtml = `
      <div class="wizard-complete-playlist">
        <h4 style="color: var(--text-gold); margin-top: 0;">Saved upgrade ideas</h4>
        <p class="muted" style="font-size: 0.9rem; line-height: 1.45;">Kept for future refinement — acquire these over time to push closer to the original optimal list.</p>
        ${wizardPlaylistPanelHtml()}
      </div>
    `;

    let shoppingListHtml = "";
    if (missing.length === 0) {
      shoppingListHtml = `
        <div style="background: rgba(74, 222, 128, 0.1); border: 1px solid rgba(74, 222, 128, 0.3); padding: 1.5rem; border-radius: 6px; text-align: center; margin-bottom: 1.5rem;">
          <h4 style="color: #4ade80; margin-top: 0; margin-bottom: 0.5rem;">Fully owned list</h4>
          <p class="muted" style="margin: 0;">Every card in this deck is already in your collection.</p>
        </div>
      `;
    } else {
      let itemsHtml = "";
      missing.forEach(row => {
        const title = row.card;
        const info = lookupCard(title);
        const unit = row.estimated_unit_price == null ? 0 : Number(row.estimated_unit_price);
        const cost = row.estimated_missing_cost == null ? 0 : Number(row.estimated_missing_cost);
        const tcgUrl = row.tcgplayer_url || "";

        const previewAttrs = info ? `
          data-preview-title="${escAttr(title)}"
          data-preview-image="${escAttr(info.imageUrl || "")}"
          data-preview-meta="${escAttr(cardMetaLine(info))}"
          data-preview-stats="${escAttr(cardStatsLine(info))}"
          data-preview-fallback="${escAttr(initials(title))}"
        ` : "";

        itemsHtml += `
          <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-gold); padding: 0.75rem 0; gap: 1rem;">
            <div style="display: flex; flex-direction: column; gap: 0.25rem;">
              <span class="wizard-card-link" ${previewAttrs} style="font-weight: bold; text-decoration: underline; cursor: help; color: var(--text-gold);">${esc(title)}</span>
              <span class="muted" style="font-size: 0.8rem;">Need ${row.missing} of ${row.required} (Owned ${row.owned})</span>
            </div>
            <div style="text-align: right; display: flex; align-items: center; gap: 1rem;">
              <span style="font-weight: 500;">Est: $${cost.toFixed(2)} ${unit > 0 ? `($${unit.toFixed(2)} ea)` : ''}</span>
              ${tcgUrl ? `<a class="card-action-btn primary" href="${escAttr(tcgUrl)}" target="_blank" rel="noopener noreferrer" style="padding: 0.35rem 0.75rem; text-decoration: none; font-size: 0.8rem;">Buy</a>` : ''}
            </div>
          </div>
        `;
      });

      shoppingListHtml = `
        <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 1rem;">Optional acquisitions</h4>
          <p class="muted" style="font-size: 0.9rem; margin-bottom: 1rem;">Cards still short in this finalized list (not required to keep refining).</p>
          <div style="max-height: 300px; overflow-y: auto; padding-right: 0.5rem; margin-bottom: 1.5rem;">
            ${itemsHtml}
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border-gold); padding-top: 1rem; font-weight: bold; font-size: 1.1rem; color: var(--text-gold);">
            <span>Estimated Total Purchase Cost:</span>
            <span>$${(estCost || 0).toFixed(2)}</span>
          </div>
        </div>
      `;
    }

    let tradeSuggestionsHtml = "";
    if (state.wizard.decisions && state.wizard.decisions.length > 0) {
      let rowsHtml = "";
      state.wizard.decisions.forEach(dec => {
        rowsHtml += `
          <div style="padding: 0.5rem 0; border-bottom: 1px dashed var(--border-gold); font-size: 0.9rem; line-height: 1.4;">
            Replaced <strong>${esc(dec.original)}</strong> with <strong>${esc(dec.replacedWith)}</strong>.
          </div>
        `;
      });
      tradeSuggestionsHtml = `
        <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 1rem;">Trade Suggestions</h4>
          <p class="muted" style="font-size: 0.9rem; margin-bottom: 1rem; line-height: 1.4;">
            To optimize your deck toward the original synergy template, consider trading away or trading for the following:
          </p>
          <div style="margin-bottom: 1rem; max-height: 200px; overflow-y: auto;">
            ${rowsHtml}
          </div>
          <div style="font-size: 0.85rem; background: rgba(212, 175, 55, 0.05); padding: 0.75rem; border-radius: 4px; border-left: 3px solid var(--text-gold); line-height: 1.4;">
            <strong>Local Trade Tips:</strong> Seek local trade groups. Champions and Legends are high-value trade targets. 
            Typical store trade-in values are 60-70% of market price, but trading directly with local players often yields 100% value-for-value swaps.
          </div>
        </div>
      `;
    } else {
      tradeSuggestionsHtml = `
        <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 0.5rem;">Trade Suggestions</h4>
          <p class="muted" style="margin: 0; font-size: 0.9rem; line-height: 1.4;">
            No card replacements were made! Your deck matches the synergy model. Trade options are not necessary unless you need to acquire the base cards in the shopping list.
          </p>
        </div>
      `;
    }

    let synergyUpgradeHtml = "";
    if (state.wizard.decisions && state.wizard.decisions.length > 0) {
      const upgradeRows = state.wizard.decisions.map(dec => {
        const orig = dec.original;
        const repl = dec.replacedWith;
        const origInfo = lookupCard(orig);

        const previewAttrs = origInfo ? `
          data-preview-title="${escAttr(orig)}"
          data-preview-image="${escAttr(origInfo.imageUrl || "")}"
          data-preview-meta="${escAttr(cardMetaLine(origInfo))}"
          data-preview-stats="${escAttr(cardStatsLine(origInfo))}"
          data-preview-fallback="${escAttr(initials(orig))}"
        ` : "";

        return `
          <li style="margin-bottom: 0.75rem; line-height: 1.4;">
            Revert <strong>${esc(repl)}</strong> to <span class="wizard-card-link" ${previewAttrs} style="font-weight: bold; text-decoration: underline; cursor: help; color: var(--text-gold);">${esc(orig)}</span>
          </li>
        `;
      }).join("");

      const improvement = Math.max(0, targetScore - currentScore);
      const improvementText = improvement > 0
        ? `<div style="margin-top: 1rem; color: #4ade80; font-weight: 500; font-size: 0.95rem;">🔥 Reverting swaps will boost competitive score by +${Math.round(improvement * 100)}%!</div>`
        : "";

      synergyUpgradeHtml = `
        <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 0.5rem;">Synergy Upgrade Guide</h4>
          <p class="muted" style="font-size: 0.9rem; margin-bottom: 1rem; line-height: 1.4;">
            Your custom replacements perform well, but upgrading to the original cards increases predicted deck quality.
          </p>
          <div style="display: flex; gap: 1rem; align-items: center; background: rgba(0, 0, 0, 0.2); padding: 1rem; border-radius: 6px; margin-bottom: 1.5rem;">
            <div style="flex: 1; text-align: center; border-right: 1px solid var(--border-gold);">
              <div class="muted" style="font-size: 0.75rem; margin-bottom: 0.25rem;">Current Custom Deck</div>
              <div style="font-size: 1.3rem; font-weight: bold; color: var(--text-gold);">${Math.round(currentScore * 100)}%</div>
            </div>
            <div style="flex: 1; text-align: center;">
              <div class="muted" style="font-size: 0.75rem; margin-bottom: 0.25rem;">Original Target Deck</div>
              <div style="font-size: 1.3rem; font-weight: bold; color: var(--text-gold);">${Math.round(targetScore * 100)}%</div>
            </div>
          </div>
          <ul style="padding-left: 1.25rem; margin: 0;">
            ${upgradeRows}
          </ul>
          ${improvementText}
        </div>
      `;
    } else {
      synergyUpgradeHtml = `
        <div style="background: var(--bg-card); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
          <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 0.5rem;">Synergy Upgrade Guide</h4>
          <p class="muted" style="margin: 0; font-size: 0.9rem; line-height: 1.4;">
            Your deck is 100% matched to the synergistic target deck (Competitive rating: ${Math.round(targetScore * 100)}%). No synergy upgrades are needed!
          </p>
        </div>
      `;
    }

    const defaultDeckName = `Guided ${state.wizard.deck.legendTitle || 'Wizard'} Deck`;
    const rightPaneHtml = `
      <div style="background: var(--bg-paper); border: 1px solid var(--border-gold); padding: 1.5rem; border-radius: 8px;">
        <h4 style="color: var(--text-gold); margin-top: 0; margin-bottom: 1rem;">Save Deck to Library</h4>
        <div style="margin-bottom: 1.25rem;">
          <label style="display: block; font-weight: bold; margin-bottom: 0.5rem; font-size: 0.9rem;">Deck Name:</label>
          <input id="wizard-save-name" type="text" value="${escAttr(defaultDeckName)}" style="width: 100%; padding: 0.6rem; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-gold); border-radius: 4px;">
        </div>
        <div style="margin-bottom: 1.5rem;">
          <label style="display: block; font-weight: bold; margin-bottom: 0.5rem; font-size: 0.9rem;">Visibility:</label>
          <select id="wizard-save-visibility" style="width: 100%; padding: 0.6rem; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-gold); border-radius: 4px;">
            <option value="private">Private (Only You)</option>
            <option value="public">Public (Meta Index)</option>
          </select>
        </div>
        <button id="wizard-save-deck-btn" type="button" class="primary" style="width: 100%; padding: 1rem; font-size: 1.05rem; font-weight: bold;">
          Save Deck 💾
        </button>
      </div>
    `;

    container.innerHTML = `
      <div class="wizard-complete-pane">
        <div style="margin-bottom: 2rem;">
          <h3 style="color: var(--text-gold); margin-top: 0; margin-bottom: 0.5rem;">Strongest deck ready</h3>
          <p class="muted" style="margin: 0;">Your best build for this legend with your collection. Save it to your library; upgrade ideas stay for future passes.</p>
        </div>

        <div style="display: flex; gap: 2rem; flex-wrap: wrap;">
          <div style="flex: 1 1 500px;">
            ${iterationSummaryHtml}
            ${playlistHtml}
            ${shoppingListHtml}
            ${tradeSuggestionsHtml}
            ${synergyUpgradeHtml}
          </div>
          <div style="flex: 1 1 300px; align-self: flex-start; position: sticky; top: 1rem;">
            ${rightPaneHtml}
          </div>
        </div>
      </div>
    `;

    bindPreviewInteractions(container);

    const saveBtn = document.getElementById("wizard-save-deck-btn");
    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        const nameInput = document.getElementById("wizard-save-name");
        const name = nameInput ? nameInput.value.trim() : defaultDeckName;
        const visSelect = document.getElementById("wizard-save-visibility");
        const visibility = visSelect ? visSelect.value : "private";

        void withBusy(saveBtn, "Saving Deck...", async () => {
          try {
            const validation = await validateWizardDeckPayload(state.wizard.deck);
            if (!validation || !validation.is_valid) {
              const firstIssue = validation && Array.isArray(validation.issues) && validation.issues[0]
                ? validation.issues[0].code
                : "VALIDATION";
              setStatus(`Save blocked: current wizard deck is illegal (${firstIssue}).`, true);
              return;
            }
            await api("/api/decks/library", {
              method: "POST",
              body: {
                name: name || defaultDeckName,
                source: "wizard",
                bucket: "saved",
                visibility: visibility,
                deck: state.wizard.deck
              }
            });
            await loadLibrary();
            setStatus(`Saved guided deck: ${name || defaultDeckName}`, false);
            setWorkspaceTab("deck");
          } catch (e) {
            console.error("Failed to save wizard deck:", e);
            setStatus(e.message || "Could not save deck to library.", true);
          }
        });
      });
    }
  }

  async function init() {
    closePicker();
    closeReplacementModal();
    closeMainCardModal();
    closeMetaDetailModal();
    closeDeckImportModal();
    if (bootWorkspaceHint() === "model-observation" || isModelObservationPath(window.location.pathname)) {
      state.ui.workspaceTab = "model-observation";
    }
    bindEvents();
    applyDiscoverTab();
    applyWorkspaceTab();
    renderAuthShell();
    try {
      const authenticated = await initializeAuth();
      if (!authenticated) return;
      applyWorkspaceTab();
      applyDiscoverTab();
      await loadInitialWorkspace();
    } catch (err) {
      state.auth.status = "error";
      renderAuthShell();
      setAuthMessage(err.message || "Startup load failed.", true);
      setStatus(err.message || "Startup load failed.", true);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    void init();
  }
})();
