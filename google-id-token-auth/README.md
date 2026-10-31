# Google ID Token Authentication Demo & System Design Lab

An interactive OpenID Connect (OIDC) identity application demonstrating the complete identity verification flow from the browser through Google Login, receiving a Google ID Token, validating it on a localhost application backend, and extracting and displaying user identity.

```
+---------------------+         1. User Click / Login         +--------------------------+
|                     | ------------------------------------> |                          |
|  Developer/Browser  |                                       |      Google Accounts     |
|   (localhost:8005)  | <------------------------------------ |      (OAuth 2.0/OIDC)    |
|                     |         2. Google ID Token (JWT)      +--------------------------+
+---------------------+                                                     |
        |                                                                   |
        | 3. POST /api/auth/google-login                                    |
        v                                                                   |
+---------------------+         4. Fetch Public JWKS Keys                   |
|  Your Application   | ----------------------------------------------------+
|  Backend (FastAPI)  |    (https://www.googleapis.com/oauth2/v3/certs)
|                     |
|  * RS256 Verify Sig |
|  * aud == Client ID |
|  * iss == Google    |
|  * exp > now        |
|  * Extract Identity |
|  * Establish Session|
+---------------------+
        |
        | 5. Return Verified Profile & Session Token
        v
+---------------------+
|  Display to User    |
|  * Avatar & Name    |
|  * Verified Email   |
|  * Permanent 'sub'  |
+---------------------+
```

---

## Features

- **Interactive System Visualizer**: A 4-stage pipeline ribbon visually tracking authentication packets across Developer/Browser, Google Login, Google ID Token, and Your Application (localhost).
- **Dual Authentication Modes**:
  1. **1-Click Simulator Mode**: Generates authentic RSA-signed OIDC ID tokens mimicking Google's identity payload so you can immediately test the entire verification lifecycle without needing Google Cloud credentials.
  2. **Live Google Sign-In**: Uses Google Identity Services (GIS) SDK. Enter your Google Web Client ID to sign in directly with your personal or Google Workspace account.
  3. **Manual Token Inspector**: Paste any external Google ID Token string to verify against Google's live rotating JWKS public keys.
- **Color-Coded JWT Inspector**: Visualizes the 3 components of the RFC 7519 token: Header (Red), Payload (Purple), and RS256 Signature (Cyan).
- **Cryptographic Verification Audit**:
  - Live signature verification against Google's rotating public keys at `https://www.googleapis.com/oauth2/v3/certs`.
  - Strict Audience (`aud`) check to prevent token substitution attacks.
  - Issuer (`iss`) check against `accounts.google.com`.
  - Expiration (`exp`) check with live countdown.
- **Localhost Session Establishment**: Demonstrates how "Your Application (localhost)" creates an internal session token from the verified Google subject identity and protects internal endpoints (`GET /api/me`).
- **Complete Decoded Claims Inspector**: Tabular view of all OpenID Connect claims (`sub`, `email`, `email_verified`, `name`, `picture`, `given_name`, `family_name`, `iat`, `exp`, `locale`).

---

## Quick Start

### Option 1: Docker Compose (Recommended)

```sh
cd google-id-token-auth
docker compose up --build
```

Open your browser to:
```
http://localhost:8005
```

To run the automated security and verification test suite:
```sh
docker compose --profile test run --rm tests
```

---

### Option 2: Run Locally with Python

```sh
cd google-id-token-auth

# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

---

## Configuring Real Google Cloud Credentials (Optional)

To enable live Google Sign-In with your real Google account on `localhost`:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Navigate to **APIs & Services** &rarr; **Credentials**.
4. Click **Create Credentials** &rarr; **OAuth client ID**.
5. Select Application type: **Web application**.
6. Set **Authorized JavaScript origins**:
   - `http://localhost:8005`
   - `http://127.0.0.1:8005`
7. Set **Authorized redirect URIs**:
   - `http://localhost:8005`
   - `http://127.0.0.1:8005`
8. Copy the generated **Client ID** (e.g. `123456789012-abcdef.apps.googleusercontent.com`).
9. Paste it into the UI's configuration box, or set `GOOGLE_CLIENT_ID` in your `.env` file:
   ```sh
   GOOGLE_CLIENT_ID=123456789012-abcdef.apps.googleusercontent.com
   ```

---

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Interactive Web Visualizer Application |
| `GET` | `/architecture` | Deep-dive OpenID Connect & Security specification |
| `GET` | `/api/config` | Returns client configuration and demo mode status |
| `POST` | `/api/auth/google-login` | Receives `{ id_token: "..." }`, validates signature against Google JWKS, returns verified identity |
| `POST` | `/api/auth/simulate` | Generates a valid test OIDC ID token and verifies it |
| `GET` | `/api/me` | Protected localhost endpoint requiring `Authorization: Bearer <session_token>` |
| `GET` | `/api/jwks-info` | Returns active public key metadata from Google's live certs endpoint |
| `GET` | `/healthz` | Liveness health check |

---

## Security Considerations

1. **Why Audience (`aud`) Verification is Critical:**
   If your server only verifies that the token was signed by Google without checking `aud`, an attacker could obtain a valid Google ID token for *another* application (e.g. `attacker-app.com`) and submit it to *your* application. Because Google signed both, your server would mistake the attacker's token as valid for your site. Enforcing `aud == YOUR_CLIENT_ID` prevents this token substitution attack.

2. **Always Use `sub` as the Primary Identifier:**
   Google account email addresses can be changed by users (e.g., in Google Workspace or account renames). The `sub` (Subject) claim is an immutable 21+ digit identifier that never changes for the lifetime of that Google account.

3. **Cache JWKS with TTL:**
   Google regularly rotates its RSA keypairs. Your application caches public keys retrieved from `https://www.googleapis.com/oauth2/v3/certs` to ensure fast verifications without introducing external HTTP latency to every login request.
