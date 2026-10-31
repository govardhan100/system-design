/**
 * Google ID Token Identity Demo
 * Handles Google Identity Services SDK, Simulator, Localhost Verification, and Flow Visualization.
 */

// Application State
let currentClientId = "";
let currentSessionToken = null;
let currentRawToken = null;

// Claim Purpose Dictionary (RFC 7519 & OpenID Connect Core 1.0)
const CLAIM_DESCRIPTIONS = {
  iss: "Issuer: Authentication authority that issued and signed the token (https://accounts.google.com).",
  sub: "Subject: Unique, immutable identifier for the user account across Google services. Never changes.",
  azp: "Authorized Party: The OAuth Client ID of the authorized client application.",
  aud: "Audience: Intended recipient of the token; MUST match your application's Google Client ID.",
  email: "User Email: User's primary Google account email address.",
  email_verified: "Email Verification: Boolean flag confirming Google verified ownership of the email.",
  name: "Full Name: User's full display name.",
  picture: "Avatar URL: Link to user's public Google profile photo.",
  given_name: "First Name: User's given name.",
  family_name: "Last Name: User's family/surname.",
  locale: "Locale: BCP47 language/locale preference (e.g. 'en').",
  iat: "Issued At: UNIX timestamp when Google created and signed this token.",
  exp: "Expiration: UNIX timestamp when token expires. Localhost verifier rejects exp <= now.",
  jti: "JWT ID: Unique token transaction identifier preventing replay attacks.",
  at_hash: "Access Token Hash: OIDC hash verifying token binding to an access token.",
  hd: "Hosted Domain: Google Workspace enterprise domain (e.g. company.com) if applicable."
};

// DOM Elements
const step1 = document.getElementById("step-node-1");
const step2 = document.getElementById("step-node-2");
const step3 = document.getElementById("step-node-3");
const step4 = document.getElementById("step-node-4");

const clientIdInput = document.getElementById("google-client-id-input");
const saveClientIdBtn = document.getElementById("save-client-id-btn");
const modeBadge = document.getElementById("mode-badge");

const tabBtnSim = document.getElementById("tab-btn-sim");
const tabBtnGoogle = document.getElementById("tab-btn-google");
const tabBtnManual = document.getElementById("tab-btn-manual");
const paneSim = document.getElementById("pane-sim");
const paneGoogle = document.getElementById("pane-google");
const paneManual = document.getElementById("pane-manual");

const runSimBtn = document.getElementById("run-sim-btn");
const simExpiredBtn = document.getElementById("sim-expired-btn");
const verifyManualBtn = document.getElementById("verify-manual-btn");
const manualTokenInput = document.getElementById("manual-token-input");

const jwtColoredBox = document.getElementById("jwt-colored-box");
const copyTokenBtn = document.getElementById("copy-token-btn");

const identityEmptyState = document.getElementById("identity-empty-state");
const userProfileView = document.getElementById("user-profile-view");
const userAvatar = document.getElementById("user-avatar");
const userFullName = document.getElementById("user-full-name");
const userEmail = document.getElementById("user-email");
const userSubId = document.getElementById("user-sub-id");
const emailVerifiedBadge = document.getElementById("email-verified-badge");
const authStateBadge = document.getElementById("auth-state-badge");

const testProtectedBtn = document.getElementById("test-protected-btn");
const protectedResponseBox = document.getElementById("protected-response-box");
const protectedResponseCode = document.getElementById("protected-response-code");
const clearSessionBtn = document.getElementById("clear-session-btn");

const claimsTbody = document.getElementById("claims-tbody");
const claimsCountBadge = document.getElementById("claims-count-badge");
const fetchJwksBtn = document.getElementById("fetch-jwks-btn");
const jwksPreview = document.getElementById("jwks-keys-preview");

// Initialize application on load
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupPresetPills();
  await fetchConfig();
  await fetchJwksInfo();
  setupEventListeners();
});

// Fetch backend config
async function fetchConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    if (data.google_client_id) {
      currentClientId = data.google_client_id;
      clientIdInput.value = currentClientId;
      modeBadge.textContent = "Google Live Client Active";
      modeBadge.className = "badge badge-success";
      initGoogleSignInSDK(currentClientId);
    } else {
      modeBadge.textContent = "Simulator Mode Active";
    }
  } catch (err) {
    console.warn("Could not fetch server config:", err);
  }
}

// Google Identity Services SDK initialization
function initGoogleSignInSDK(clientId) {
  if (!clientId || typeof google === "undefined" || !google.accounts) {
    return;
  }

  try {
    const gsiWarning = document.getElementById("gsi-warning");
    if (gsiWarning) gsiWarning.style.display = "none";

    google.accounts.id.initialize({
      client_id: clientId,
      callback: handleGoogleCredentialResponse,
      auto_select: false,
      cancel_on_tap_outside: true
    });

    const buttonTarget = document.getElementById("g_id_signin_placeholder");
    if (buttonTarget) {
      buttonTarget.innerHTML = "";
      google.accounts.id.renderButton(buttonTarget, {
        theme: "filled_blue",
        size: "large",
        shape: "rectangular",
        logo_alignment: "left",
        text: "signin_with"
      });
    }
  } catch (e) {
    console.error("Error initializing Google Identity Services:", e);
  }
}

// Callback invoked when user logs in with Google button
async function handleGoogleCredentialResponse(response) {
  const idToken = response.credential;
  if (!idToken) return;

  animateFlowPipeline();
  await verifyTokenWithLocalhost(idToken);
}

// Tab navigation
function setupTabs() {
  const tabs = [
    { btn: tabBtnSim, pane: paneSim },
    { btn: tabBtnGoogle, pane: paneGoogle },
    { btn: tabBtnManual, pane: paneManual }
  ];

  tabs.forEach(({ btn, pane }) => {
    btn.addEventListener("click", () => {
      tabs.forEach(t => {
        t.btn.classList.remove("active");
        t.pane.classList.remove("active");
      });
      btn.classList.add("active");
      pane.classList.add("active");
    });
  });
}

// Preset persona pills
function setupPresetPills() {
  document.querySelectorAll(".pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("sim-name-input").value = btn.dataset.name;
      document.getElementById("sim-email-input").value = btn.dataset.email;
    });
  });
}

// Event Listeners
function setupEventListeners() {
  saveClientIdBtn.addEventListener("click", () => {
    currentClientId = clientIdInput.value.trim();
    if (currentClientId) {
      initGoogleSignInSDK(currentClientId);
      tabBtnGoogle.click();
      modeBadge.textContent = "Live Client ID Configured";
      modeBadge.className = "badge badge-success";
    } else {
      modeBadge.textContent = "Simulator Mode Active";
      modeBadge.className = "badge badge-info";
    }
  });

  runSimBtn.addEventListener("click", async () => {
    const name = document.getElementById("sim-name-input").value;
    const email = document.getElementById("sim-email-input").value;
    animateFlowPipeline();

    try {
      runSimBtn.disabled = true;
      runSimBtn.innerHTML = "Generating & Verifying...";
      const res = await fetch("/api/auth/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name,
          email: email,
          client_id: currentClientId || null,
          expired: false
        })
      });
      const data = await res.json();
      renderVerificationResponse(data);
    } catch (err) {
      alert("Error simulating token: " + err);
    } finally {
      runSimBtn.disabled = false;
      runSimBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        Generate & Verify Token
      `;
    }
  });

  simExpiredBtn.addEventListener("click", async () => {
    animateFlowPipeline();
    try {
      const res = await fetch("/api/auth/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "Expired User",
          email: "expired.session@demo.com",
          expired: true
        })
      });
      const data = await res.json();
      renderVerificationResponse(data);
    } catch (err) {
      alert("Error simulating expired token: " + err);
    }
  });

  verifyManualBtn.addEventListener("click", async () => {
    const token = manualTokenInput.value.trim();
    if (!token) {
      alert("Please enter or paste a JWT token.");
      return;
    }
    animateFlowPipeline();
    await verifyTokenWithLocalhost(token);
  });

  copyTokenBtn.addEventListener("click", () => {
    if (!currentRawToken) return;
    navigator.clipboard.writeText(currentRawToken).then(() => {
      copyTokenBtn.textContent = "Copied!";
      setTimeout(() => (copyTokenBtn.textContent = "Copy Token"), 1500);
    });
  });

  testProtectedBtn.addEventListener("click", async () => {
    if (!currentSessionToken) {
      alert("No active localhost session token.");
      return;
    }
    try {
      testProtectedBtn.disabled = true;
      testProtectedBtn.textContent = "Calling GET /api/me...";
      const res = await fetch("/api/me", {
        headers: { Authorization: `Bearer ${currentSessionToken}` }
      });
      const data = await res.json();
      protectedResponseBox.classList.remove("hidden");
      protectedResponseCode.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      alert("Failed to call protected endpoint: " + err);
    } finally {
      testProtectedBtn.disabled = false;
      testProtectedBtn.textContent = "Test Protected Endpoint (GET /api/me)";
    }
  });

  clearSessionBtn.addEventListener("click", resetSession);
  fetchJwksBtn.addEventListener("click", fetchJwksInfo);
}

// Verify token with backend
async function verifyTokenWithLocalhost(idToken) {
  try {
    const res = await fetch("/api/auth/google-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id_token: idToken,
        client_id: currentClientId || null
      })
    });
    const data = await res.json();
    renderVerificationResponse(data);
  } catch (err) {
    alert("Verification network error: " + err);
  }
}

// Animate 4-step pipeline ribbon
function animateFlowPipeline() {
  const steps = [step1, step2, step3, step4];
  steps.forEach(s => s.classList.remove("active"));

  step1.classList.add("active");
  setTimeout(() => step2.classList.add("active"), 200);
  setTimeout(() => step3.classList.add("active"), 450);
  setTimeout(() => step4.classList.add("active"), 700);
}

// Render verification results & identity card
function renderVerificationResponse(res) {
  // Update raw token display
  renderRawJwt(res);

  if (!res.success) {
    authStateBadge.textContent = "Verification Failed";
    authStateBadge.className = "badge badge-danger";
    identityEmptyState.classList.remove("hidden");
    userProfileView.classList.add("hidden");
    alert("Token Verification Failed: " + res.message);
    return;
  }

  // Success
  currentSessionToken = res.session_token;
  authStateBadge.textContent = res.is_simulated ? "Verified (Simulated OIDC)" : "Verified (Google Live)";
  authStateBadge.className = "badge badge-success";

  // Hide empty state, reveal profile
  identityEmptyState.classList.add("hidden");
  userProfileView.classList.remove("hidden");
  protectedResponseBox.classList.add("hidden");

  // Populate user profile info
  const user = res.user;
  userFullName.textContent = user.name || "Google User";
  userEmail.textContent = user.email;
  userSubId.textContent = user.sub;
  if (user.picture) {
    userAvatar.src = user.picture;
  } else {
    userAvatar.src = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&q=80";
  }

  // Security Checklist
  const report = res.verification_report;
  if (report) {
    updateCheckItem("check-signature", report.signature_valid, `Method: ${report.verification_method} (kid: ${report.key_id || 'N/A'})`);
    updateCheckItem("check-issuer", report.issuer_valid, report.issuer);
    updateCheckItem("check-audience", report.audience_valid, report.audience);
    const mins = Math.max(0, Math.floor(report.time_to_expiry_sec / 60));
    updateCheckItem("check-expiry", report.expiry_valid, report.expiry_valid ? `Valid (${mins}m remaining)` : "Expired!");
  }

  // Populate Claims Table
  renderClaimsTable(res.raw_claims);
}

function updateCheckItem(elementId, passed, detailText) {
  const el = document.getElementById(elementId);
  const detail = el.querySelector(".check-detail");
  const icon = el.querySelector(".check-icon");

  if (passed) {
    el.className = "check-item passed";
    icon.innerHTML = "&check;";
  } else {
    el.className = "check-item failed";
    icon.innerHTML = "&times;";
  }
  if (detailText) detail.textContent = detailText;
}

// Render colored JWT string
function renderRawJwt(res) {
  const tokenStr = res.raw_token || manualTokenInput.value.trim();

  // If token has standard 3-part JWT structure
  if (tokenStr && tokenStr.split(".").length === 3) {
    currentRawToken = tokenStr;
    const [h, p, s] = tokenStr.split(".");
    jwtColoredBox.innerHTML = `
      <span class="jwt-seg-header" title="Header (Algorithm & Key ID)">${escapeHtml(h)}</span>
      <span class="jwt-dot">.</span>
      <span class="jwt-seg-payload" title="Payload (Identity Claims)">${escapeHtml(p)}</span>
      <span class="jwt-dot">.</span>
      <span class="jwt-seg-signature" title="RS256 Cryptographic Signature">${escapeHtml(s)}</span>
    `;
  } else if (res.header && res.raw_claims) {
    // Format JSON representation fallback
    const headerBase = btoa(JSON.stringify(res.header)).replace(/=/g, "");
    const payloadBase = btoa(JSON.stringify(res.raw_claims)).replace(/=/g, "");
    const sigSample = "Kz87x291_DEMO_RSA_SIGNATURE_BYTES_4a8b1c9d2e";
    currentRawToken = `${headerBase}.${payloadBase}.${sigSample}`;
    jwtColoredBox.innerHTML = `
      <span class="jwt-seg-header" title="Header">${headerBase}</span>
      <span class="jwt-dot">.</span>
      <span class="jwt-seg-payload" title="Payload">${payloadBase}</span>
      <span class="jwt-dot">.</span>
      <span class="jwt-seg-signature" title="Signature">${sigSample}</span>
    `;
  }
}

// Render Claims Table
function renderClaimsTable(claims) {
  claimsTbody.innerHTML = "";
  const keys = Object.keys(claims || {});
  claimsCountBadge.textContent = `${keys.length} claims`;

  keys.forEach(key => {
    const val = claims[key];
    const desc = CLAIM_DESCRIPTIONS[key] || "Custom or standard OpenID Connect claim.";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><code class="claim-key-code">${escapeHtml(key)}</code></td>
      <td><code class="claim-val-code">${escapeHtml(String(val))}</code></td>
      <td class="claim-desc">${escapeHtml(desc)}</td>
    `;
    claimsTbody.appendChild(tr);
  });
}

// Fetch Google JWKS info
async function fetchJwksInfo() {
  try {
    jwksPreview.innerHTML = `<span class="text-muted">Fetching Google JWKS certs...</span>`;
    const res = await fetch("/api/jwks-info");
    const data = await res.json();

    if (data.keys && data.keys.length > 0) {
      jwksPreview.innerHTML = data.keys.map(k => `
        <span class="jwks-key-badge" title="RSA Public Key">
          <strong>kid:</strong> <code>${k.kid}</code> &bull;
          <span>${k.kty} / ${k.alg}</span>
        </span>
      `).join("");
    } else {
      jwksPreview.innerHTML = `<span class="text-muted">Could not load keys (${data.error || 'unknown'})</span>`;
    }
  } catch (err) {
    jwksPreview.innerHTML = `<span class="text-muted">JWKS offline or unreachable: ${err}</span>`;
  }
}

// Reset session
function resetSession() {
  currentSessionToken = null;
  currentRawToken = null;
  identityEmptyState.classList.remove("hidden");
  userProfileView.classList.add("hidden");
  authStateBadge.textContent = "Waiting For Auth";
  authStateBadge.className = "badge badge-info";
  jwtColoredBox.innerHTML = `<span class="jwt-placeholder">Awaiting Google ID Token authentication...</span>`;
  protectedResponseBox.classList.add("hidden");
  step1.classList.add("active");
  step2.classList.remove("active");
  step3.classList.remove("active");
  step4.classList.remove("active");
}

function escapeHtml(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}
