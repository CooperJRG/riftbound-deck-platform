(function (global) {
  const SESSION_PREFIX = "riftbound.supabase.session:";

  function authHeaders(anonKey, accessToken) {
    const headers = {
      apikey: String(anonKey || ""),
      "Content-Type": "application/json"
    };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return headers;
  }

  function sessionKey(url) {
    return `${SESSION_PREFIX}${String(url || "").trim()}`;
  }

  function readSession(url) {
    try {
      const raw = global.localStorage.getItem(sessionKey(url));
      return raw ? JSON.parse(raw) : null;
    } catch (_err) {
      return null;
    }
  }

  function writeSession(url, session) {
    try {
      if (!session) {
        global.localStorage.removeItem(sessionKey(url));
        return;
      }
      global.localStorage.setItem(sessionKey(url), JSON.stringify(session));
    } catch (_err) {
      // Ignore storage failures and keep the in-memory session.
    }
  }

  function normalizeSession(session) {
    if (!session || typeof session !== "object") return null;
    const next = { ...session };
    const expiresAt = Number(next.expires_at);
    const expiresIn = Number(next.expires_in);
    if (!Number.isFinite(expiresAt) && Number.isFinite(expiresIn) && expiresIn > 0) {
      next.expires_at = Math.floor(Date.now() / 1000) + expiresIn;
    }
    return next;
  }

  function isSessionExpired(session) {
    const expiresAt = Number(session && session.expires_at);
    if (!Number.isFinite(expiresAt)) return false;
    return expiresAt <= Math.floor(Date.now() / 1000) + 30;
  }

  function createClient(url, anonKey) {
    const baseUrl = String(url || "").replace(/\/+$/, "");
    const listeners = [];
    let currentSession = normalizeSession(readSession(baseUrl));

    function emit(eventName) {
      listeners.slice().forEach((listener) => {
        try {
          listener(eventName, currentSession);
        } catch (_err) {
          // Ignore listener failures to keep auth flow usable.
        }
      });
    }

    async function request(path, payload, accessToken) {
      const response = await fetch(`${baseUrl}${path}`, {
        method: "POST",
        headers: authHeaders(anonKey, accessToken),
        body: JSON.stringify(payload || {})
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const raw = body && (body.msg || body.error_description || body.error || body.message);
        const message = typeof raw === "string" ? raw : raw ? JSON.stringify(raw) : (response.statusText || "Supabase auth request failed.");
        return { data: null, error: { message } };
      }
      return { data: body, error: null };
    }

    async function refreshSession() {
      if (!currentSession || !currentSession.refresh_token) {
        currentSession = null;
        writeSession(baseUrl, null);
        return { data: { session: null }, error: null };
      }
      const result = await request("/auth/v1/token?grant_type=refresh_token", { refresh_token: currentSession.refresh_token });
      if (result.error) {
        currentSession = null;
        writeSession(baseUrl, null);
        emit("SIGNED_OUT");
        return { data: { session: null }, error: result.error };
      }
      currentSession = normalizeSession(result.data || null);
      writeSession(baseUrl, currentSession);
      emit("TOKEN_REFRESHED");
      return { data: { session: currentSession, user: currentSession && currentSession.user ? currentSession.user : null }, error: null };
    }

    return {
      auth: {
        async getSession() {
          currentSession = normalizeSession(readSession(baseUrl));
          if (isSessionExpired(currentSession)) {
            return refreshSession();
          }
          return { data: { session: currentSession }, error: null };
        },
        async signInWithPassword(credentials) {
          const payload = credentials || {};
          const result = await request("/auth/v1/token?grant_type=password", payload);
          if (result.error) return result;
          currentSession = normalizeSession(result.data || null);
          writeSession(baseUrl, currentSession);
          emit("SIGNED_IN");
          return { data: { session: currentSession, user: currentSession && currentSession.user ? currentSession.user : null }, error: null };
        },
        async resetPasswordForEmail(email) {
          const result = await request("/auth/v1/recover", { email: String(email || "").trim() });
          if (result.error) return result;
          return { data: result.data || {}, error: null };
        },
        async signOut() {
          const refreshToken = currentSession && currentSession.refresh_token ? currentSession.refresh_token : "";
          if (refreshToken) {
            await request("/auth/v1/logout", { refresh_token: refreshToken }, currentSession.access_token || "");
          }
          currentSession = null;
          writeSession(baseUrl, null);
          emit("SIGNED_OUT");
          return { error: null };
        },
        async refreshSession() {
          return refreshSession();
        },
        onAuthStateChange(callback) {
          if (typeof callback === "function") listeners.push(callback);
          return {
            data: {
              subscription: {
                unsubscribe() {
                  const index = listeners.indexOf(callback);
                  if (index >= 0) listeners.splice(index, 1);
                }
              }
            }
          };
        }
      }
    };
  }

  global.supabase = global.supabase || {};
  global.supabase.createClient = createClient;
})(window);
