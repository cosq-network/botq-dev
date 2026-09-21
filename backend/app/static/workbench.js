(() => {
  "use strict";

  const state = { token: sessionStorage.getItem("botq_token") || "", session: null };
  const $ = (id) => document.getElementById(id);
  const text = (value) => String(value ?? "");
  const lines = (value) => text(value).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);

  function status(message, isError = false) {
    const target = $(state.token ? "app-status" : "login-status");
    target.textContent = message;
    target.className = `status ${isError ? "error" : "success"}`;
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const response = await fetch(`/api/v1${path}`, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error?.message || `Request failed (${response.status})`);
    return body.data;
  }

  function projectId() {
    const value = $("project-id").value.trim();
    if (!value) throw new Error("Enter a project ID first");
    return encodeURIComponent(value);
  }

  function setAuthenticated(authenticated) {
    $("login-panel").hidden = authenticated;
    $("app-panel").hidden = !authenticated;
  }

  function badge(value) {
    const span = document.createElement("span");
    span.className = "badge";
    span.textContent = value;
    return span;
  }

  function card(title, details = []) {
    const article = document.createElement("article");
    article.className = "card";
    const heading = document.createElement("h3");
    heading.textContent = title;
    article.append(heading, ...details);
    return article;
  }

  async function login(event) {
    event.preventDefault();
    const previousToken = state.token;
    state.token = "";
    try {
      const data = await api("/auth/login", { method: "POST", body: JSON.stringify({
        organization: $("organization").value.trim(),
        email: $("email").value.trim(),
        password: $("password").value,
      }), headers: { Authorization: "" } });
      state.token = data.token;
      sessionStorage.setItem("botq_token", state.token);
      setAuthenticated(true);
      status(`Signed in as ${data.user.display_name}.`);
    } catch (error) {
      state.token = previousToken;
      status(error.message, true);
    }
  }

  async function loadMockups() {
    const items = await api(`/design/mockups?project_id=${projectId()}`);
    const target = $("mockups");
    target.replaceChildren();
    if (!items.length) { target.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "No mockups found." })); return; }
    items.forEach((item) => {
      const detail = document.createElement("p");
      detail.append(badge(item.status), document.createTextNode(` v${item.current_version} · ${item.design_reference.file_id}`));
      const link = document.createElement("a");
      link.href = item.design_reference.file_url || item.design_reference.preview_url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.design_reference.file_url ? "Open design reference" : "Penpot handoff required";
      const actions = document.createElement("div");
      actions.className = "card-actions";
      actions.append(link);
      const use = document.createElement("button");
      use.type = "button"; use.className = "secondary"; use.textContent = "Create preview";
      use.addEventListener("click", () => { $("preview-mockup-id").value = item.id; $("preview-commit").focus(); });
      actions.append(use);
      target.append(card(item.title, [detail, actions]));
    });
  }

  async function loadPreviews() {
    const items = await api(`/design/previews?project_id=${projectId()}`);
    const select = $("session-preview");
    select.replaceChildren(new Option(items.length ? "Select an active preview" : "No previews found", ""));
    const target = $("previews");
    target.replaceChildren();
    items.forEach((item) => {
      if (item.status === "active") select.append(new Option(`${item.environment} · ${item.commit_sha.slice(0, 12)}`, item.id));
      const detail = document.createElement("p");
      detail.append(badge(item.status), document.createTextNode(` ${item.environment} · commit ${item.commit_sha}`));
      const actions = document.createElement("div");
      actions.className = "card-actions";
      const open = document.createElement("a");
      open.href = item.url; open.target = "_blank"; open.rel = "noopener noreferrer"; open.textContent = "Open preview";
      actions.append(open);
      if (item.status === "active") {
        const start = document.createElement("button"); start.type = "button"; start.className = "secondary"; start.textContent = "Use for HAT";
        start.addEventListener("click", () => { select.value = item.id; $("session-criteria").focus(); }); actions.append(start);
      }
      target.append(card(`${item.environment} preview`, [detail, actions]));
    });
  }

  async function createPreview(event) {
    event.preventDefault();
    const deploy = $("preview-deploy").checked;
    const url = $("preview-url").value.trim();
    if (!deploy && !url) { status("Provide a preview URL or enable deployment provisioning.", true); return; }
    try {
      await api("/design/previews", { method: "POST", body: JSON.stringify({
        mockup_id: $("preview-mockup-id").value.trim(),
        commit_sha: $("preview-commit").value.trim(),
        url: url || undefined,
        deploy,
        environment: "preview",
        expires_at: new Date($("preview-expires").value).toISOString(),
        access_policy: { authentication: "required", data_class: "synthetic" },
      }) });
      await loadPreviews(); status("Protected preview created.");
    } catch (error) { status(error.message, true); }
  }

  async function startSession(event) {
    event.preventDefault();
    try {
      const data = await api("/design/acceptance/sessions", { method: "POST", body: JSON.stringify({
        preview_id: $("session-preview").value,
        criteria: lines($("session-criteria").value),
        scenario_guidance: lines($("session-guidance").value),
      }) });
      state.session = data; renderSession(data); status("Acceptance session started.");
    } catch (error) { status(error.message, true); }
  }

  function renderSession(session) {
    const target = $("session"); target.hidden = false; target.replaceChildren();
    const title = document.createElement("h3"); title.textContent = `Session ${session.id.slice(0, 8)} · ${session.status}`; target.append(title);
    session.criteria.forEach((criterion) => {
      const row = document.createElement("div"); row.className = "criterion";
      const label = document.createElement("span"); label.textContent = criterion.title;
      const select = document.createElement("select"); select.dataset.criterion = criterion.key;
      ["pass", "fail", "blocked", "na"].forEach((value) => select.append(new Option(value.toUpperCase(), value)));
      const existing = session.results.find((result) => result.criterion_key === criterion.key); if (existing) select.value = existing.outcome;
      row.append(label, select); target.append(row);
    });
    const actions = document.createElement("div"); actions.className = "card-actions";
    const save = document.createElement("button"); save.type = "button"; save.textContent = "Save results"; save.addEventListener("click", () => saveResults(session.id));
    const complete = document.createElement("button"); complete.type = "button"; complete.className = "secondary"; complete.textContent = "Complete session"; complete.addEventListener("click", () => completeSession(session.id));
    actions.append(save, complete); target.append(actions);
  }

  async function saveResults(sessionId) {
    try {
      for (const select of $("session").querySelectorAll("select[data-criterion]")) {
        await api(`/design/acceptance/sessions/${sessionId}/results`, { method: "POST", body: JSON.stringify({ criterion_key: select.dataset.criterion, outcome: select.value, evidence: { source: "acceptance-workbench" } }) });
      }
      state.session = await api(`/design/acceptance/sessions/${sessionId}`); renderSession(state.session); status("Acceptance results saved.");
    } catch (error) { status(error.message, true); }
  }

  async function completeSession(sessionId) {
    try { state.session = await api(`/design/acceptance/sessions/${sessionId}/complete`, { method: "POST", body: JSON.stringify({ source: "acceptance-workbench" }) }); renderSession(state.session); status(`Acceptance session ${state.session.status}.`); }
    catch (error) { status(error.message, true); }
  }

  async function loadDefects() {
    const items = await api(`/design/defects?project_id=${projectId()}`); const target = $("defects"); target.replaceChildren();
    items.forEach((item) => {
      const detail = document.createElement("p"); detail.append(badge(`${item.severity} · ${item.status}`), document.createTextNode(` ${item.actual}`));
      const actions = document.createElement("div"); actions.className = "card-actions";
      if (item.status !== "closed") {
        const fixed = document.createElement("button"); fixed.type = "button"; fixed.className = "secondary"; fixed.textContent = "Mark fixed"; fixed.addEventListener("click", () => updateDefect(item.id, "fixed")); actions.append(fixed);
        const close = document.createElement("button"); close.type = "button"; close.textContent = "Close with regression"; close.addEventListener("click", () => updateDefect(item.id, "closed")); actions.append(close);
      }
      target.append(card(item.title, [detail, actions]));
    });
    if (!items.length) target.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "No defects found." }));
  }

  async function updateDefect(id, statusValue) {
    try { await api(`/design/defects/${id}`, { method: "PATCH", body: JSON.stringify({ status: statusValue, regression_evidence: { status: "passed", command: "human-verified in acceptance workbench" } }) }); await loadDefects(); status(`Defect marked ${statusValue}.`); }
    catch (error) { status(error.message, true); }
  }

  async function createDefect(event) {
    event.preventDefault();
    try {
      await api("/design/defects", { method: "POST", body: JSON.stringify({
        project_id: $("project-id").value.trim(), session_id: state.session?.id,
        title: $("defect-name").value.trim(), severity: $("defect-severity").value,
        expected: $("defect-expected").value.trim(), actual: $("defect-actual").value.trim(),
        reproduction_steps: lines($("defect-steps").value), regression_test_required: $("defect-regression").checked,
      }) });
      event.target.reset(); $("defect-regression").checked = true; await loadDefects(); status("Defect logged.");
    } catch (error) { status(error.message, true); }
  }

  async function refresh() {
    try { await Promise.all([loadMockups(), loadPreviews(), loadDefects()]); status("Workbench refreshed."); }
    catch (error) { status(error.message, true); }
  }

  $("login-form").addEventListener("submit", login);
  $("session-form").addEventListener("submit", startSession);
  $("preview-form").addEventListener("submit", createPreview);
  $("defect-form").addEventListener("submit", createDefect);
  $("refresh").addEventListener("click", refresh);
  $("load-mockups").addEventListener("click", () => loadMockups().catch((error) => status(error.message, true)));
  $("load-previews").addEventListener("click", () => loadPreviews().catch((error) => status(error.message, true)));
  $("load-defects").addEventListener("click", () => loadDefects().catch((error) => status(error.message, true)));
  $("sign-out").addEventListener("click", () => { state.token = ""; sessionStorage.removeItem("botq_token"); setAuthenticated(false); status("Signed out."); });
  const defaultExpiry = new Date(Date.now() + 2 * 60 * 60 * 1000);
  $("preview-expires").value = new Date(defaultExpiry - defaultExpiry.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  setAuthenticated(Boolean(state.token));
})();
