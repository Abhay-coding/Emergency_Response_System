
const API_BASE = "http://127.0.0.1:8000";

const state = {
  token: null,
  user: null,
  incidents: [],
  authMode: "login"
};

const $ = (id) => document.getElementById(id);

function showNotice(message, isError = false) {
  const notice = $("notice");
  notice.textContent = message;
  notice.classList.remove("hidden", "error");
  if (isError) notice.classList.add("error");
}

function hideNotice() {
  $("notice").classList.add("hidden");
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});

  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  // Let the browser set Content-Type automatically for FormData uploads.
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  });

  const text = await response.text();
  let data = null;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object"
        ? data.detail || data.message
        : null;

    if (response.status === 401) {
      logout(false);
    }

    throw new Error(detail || `Request failed (${response.status})`);
  }

  return data;
}

function setAuthMode(mode) {
  state.authMode = mode;

  const registering = mode === "register";

  $("login-tab").classList.toggle("active", !registering);
  $("register-tab").classList.toggle("active", registering);

  $("name-label").classList.toggle("hidden", !registering);
  $("name").classList.toggle("hidden", !registering);
  $("name").required = registering;

  $("password").autocomplete = registering
    ? "new-password"
    : "current-password";

  $("auth-submit").textContent = registering
    ? "Create account"
    : "Sign in";
}

$("login-tab").addEventListener("click", () => setAuthMode("login"));
$("register-tab").addEventListener("click", () => setAuthMode("register"));

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideNotice();

  const email = $("email").value.trim();
  const password = $("password").value;

  try {
    $("auth-submit").disabled = true;

    if (state.authMode === "register") {
      const name = $("name").value.trim();

      // Matches the common registration schema. If your backend uses
      // different field names, adjust this payload to match its schema.
      await apiRequest("/auth/register", {
        method: "POST",
        body: JSON.stringify({ name, email, password })
      });

      showNotice("Account created. You can now sign in.");
      setAuthMode("login");
      $("password").value = "";
      return;
    }

    // OAuth2PasswordRequestForm expects form-encoded credentials.
    
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);

    const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
        "Content-Type": "application/x-www-form-urlencoded"
    },
    body: form.toString()
    });

    const result = await response.json();

    if (!response.ok) {
    throw new Error(
        typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail ?? result)
    );
    }

    if (!result.access_token) {
    throw new Error("No access token returned by the server.");
    }

    state.token = result.access_token;


    // Keep the token in memory only; do not persist it in localStorage.
    state.user = await apiRequest("/auth/me");

    $("auth-section").classList.add("hidden");
    $("dashboard").classList.remove("hidden");
    $("logout-button").classList.remove("hidden");
    $("user-label").textContent =
      state.user.name || state.user.email || "Signed in";

    showNotice("Signed in successfully.");
    await loadIncidents();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    $("auth-submit").disabled = false;
  }
});

function logout(showMessage = true) {
  state.token = null;
  state.user = null;
  state.incidents = [];

  $("auth-section").classList.remove("hidden");
  $("dashboard").classList.add("hidden");
  $("logout-button").classList.add("hidden");
  $("user-label").textContent = "Not signed in";

  $("incident-list").replaceChildren();
  updateStats([]);

  if (showMessage) showNotice("You have signed out.");
}

$("logout-button").addEventListener("click", () => logout());

function updateStats(incidents) {
  $("total-count").textContent = incidents.length;

  $("reported-count").textContent = incidents.filter(
    (item) => String(item.status).toLowerCase() === "reported"
  ).length;

  $("progress-count").textContent = incidents.filter(
    (item) => ["assigned", "in_progress", "in progress"].includes(
      String(item.status).toLowerCase()
    )
  ).length;

  $("resolved-count").textContent = incidents.filter(
    (item) => String(item.status).toLowerCase() === "resolved"
  ).length;

  $("incident-count").textContent =
    `${incidents.length} record${incidents.length === 1 ? "" : "s"}`;
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderIncidents(incidents) {
  const list = $("incident-list");
  list.replaceChildren();

  if (!incidents.length) {
    list.append(
      makeElement("div", "empty-state", "No incidents found.")
    );
    return;
  }

  for (const incident of incidents) {
    const card = makeElement("article", "incident-card");
    const top = makeElement("div", "incident-top");
    const heading = makeElement("div");

    heading.append(
      makeElement("h3", "", incident.title || `Incident #${incident.id}`),
      makeElement(
        "p",
        "",
        `#${incident.id} · ${incident.location || "Location not specified"}`
      )
    );

    top.append(heading);
    card.append(top);

    if (incident.description) {
      card.append(makeElement("p", "", incident.description));
    }

    const badges = makeElement("div", "badges");
    badges.append(
      makeElement("span", "badge", incident.category || "Other"),
      makeElement("span", "badge priority", incident.priority || "Normal"),
      makeElement("span", "badge status", incident.status || "Reported")
    );

    card.append(badges);

    if (incident.created_at) {
      const date = new Date(incident.created_at);
      if (!Number.isNaN(date.getTime())) {
        card.append(
          makeElement("p", "", `Submitted: ${date.toLocaleString()}`)
        );
      }
    }

    list.append(card);
  }
}

async function loadIncidents() {
  try {
    $("refresh-button").disabled = true;

    const incidents = await apiRequest("/incidents");
    state.incidents = Array.isArray(incidents) ? incidents : [];

    updateStats(state.incidents);
    renderIncidents(state.incidents);
  } catch (error) {
    showNotice(`Could not load incidents: ${error.message}`, true);
  } finally {
    $("refresh-button").disabled = false;
  }
}

$("refresh-button").addEventListener("click", loadIncidents);

$("incident-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideNotice();

  const payload = {
    title: $("title").value.trim(),
    category: $("category").value,
    location: $("location").value.trim(),
    priority: $("priority").value,
    description: $("description").value.trim()
  };

  try {
    const submitButton = event.submitter;
    if (submitButton) submitButton.disabled = true;

    await apiRequest("/incidents", {
      method: "POST",
      body: JSON.stringify(payload)
    });

    $("incident-form").reset();
    showNotice("Incident reported successfully.");
    await loadIncidents();
  } catch (error) {
    showNotice(`Could not submit incident: ${error.message}`, true);
  } finally {
    const submitButton = event.submitter;
    if (submitButton) submitButton.disabled = false;
  }
});

setAuthMode("login");
