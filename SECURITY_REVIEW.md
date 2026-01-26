# Security Review Report

**Branch:** dev
**Date:** 2026-01-26
**Reviewer:** Claude Code (Security Analysis)

---

## Vuln 1: Open Redirect in Authentication Flows

**File:** `src/portainer_dashboard/auth/router.py`
**Lines:** 89-108, 111-159, 221-251, 254-300

* **Severity:** HIGH
* **Category:** open_redirect
* **Description:** The `next` parameter from user input is used directly in redirect responses without any validation across four locations in the authentication flow. The login page GET handler (lines 89-108), login POST handler (lines 111-159), OIDC login initiation (lines 221-251), and OIDC callback (lines 254-300) all accept a user-controllable `next` parameter and pass it directly to `RedirectResponse(url=next)` without checking if it's a relative path or validating the domain.
* **Exploit Scenario:** An attacker crafts a malicious URL like `https://dashboard.example.com/auth/login?next=https://evil-site.com/phishing`. When a user clicks this link (perhaps from a phishing email), they see the legitimate login page. After successfully authenticating, they are immediately redirected to the attacker's site which can impersonate the dashboard to steal additional credentials, API keys, or session tokens. The OIDC flow is particularly dangerous as users are accustomed to external redirects during OAuth authentication.
* **Recommendation:** Implement URL validation to ensure the `next` parameter is a safe relative path:
  ```python
  def is_safe_redirect_url(url: str) -> bool:
      """Check if URL is safe for redirect (relative path only)."""
      if not url:
          return False
      # Must start with single slash, not double (protocol-relative)
      return url.startswith("/") and not url.startswith("//")

  # In each redirect location:
  redirect_url = next if is_safe_redirect_url(next) else "/"
  response = RedirectResponse(url=redirect_url, status_code=303)
  ```

---

## Vuln 2: Unauthenticated WebSocket Endpoints

**Files:**
- `src/portainer_dashboard/websocket/llm_chat.py` (lines 342-345)
- `src/portainer_dashboard/websocket/remediation.py` (lines 145-154)
- `src/portainer_dashboard/websocket/monitoring_insights.py` (lines 133-136)

* **Severity:** HIGH
* **Category:** authentication_bypass
* **Description:** All three WebSocket endpoints (`/ws/llm/chat`, `/ws/remediation`, `/ws/monitoring/insights`) accept connections without any authentication verification. Unlike REST API endpoints which use `CurrentUserDep` dependency to validate session cookies, the WebSocket handlers immediately call `await websocket.accept()` without checking for session tokens, cookies, or any form of authentication. The frontend also connects without passing authentication headers.
* **Exploit Scenario:** An attacker can connect directly to `ws://target:8000/ws/llm/chat` without any credentials. Once connected, they can send messages requesting infrastructure information. The LLM chat endpoint is particularly severe as it exposes full infrastructure context including endpoint names/status, all container details (names, images, states, resource usage), and container logs for stopped/unhealthy/restarting containers which may contain secrets, error messages, or credentials. The remediation WebSocket exposes pending actions and action history, while the monitoring WebSocket exposes AI-generated health insights and anomaly information.
* **Recommendation:** Add WebSocket authentication by extracting and validating the session cookie before accepting the connection:
  ```python
  @router.websocket("/ws/llm/chat")
  async def llm_chat_websocket(
      websocket: WebSocket,
      storage: Annotated[SessionStorage, Depends(get_session_storage)],
  ) -> None:
      token = websocket.cookies.get(SESSION_COOKIE_NAME)
      if not token:
          await websocket.close(code=4001, reason="Not authenticated")
          return
      record = storage.retrieve(token)
      if not record:
          await websocket.close(code=4001, reason="Invalid session")
          return
      await websocket.accept()
      # ... rest of handler
  ```

---

## Summary

| Finding | Severity | Category | Confidence |
|---------|----------|----------|------------|
| Open Redirect in Auth Flows | HIGH | open_redirect | 8/10 |
| Unauthenticated WebSockets | HIGH | authentication_bypass | 9/10 |

Both vulnerabilities should be addressed before production deployment.
