# User Stories for Algo Trading Web App

## User Story 1: Access Token Management
**As a user, I want to securely generate and manage my KiteConnect access token via the web app, so I can avoid manual token generation each day.**

**Acceptance Criteria:**
- The app provides a secure login flow for KiteConnect.
- The access token is generated and stored securely for the session.
- The user is notified if the token is expired or invalid.

---

## User Story 2: Trading Dashboard
**As a user, I want a dashboard that displays real-time trading activity, open positions, trade logs, and P&L, so I can monitor my algo’s performance.**

**Acceptance Criteria:**
- The dashboard shows all open and closed trades with details.
- Real-time updates for trade status, P&L, and risk limits.
- Visual indicators for daily profit/loss caps and position limits.

---

## User Story 3: Automated Trading Logic
**As a user, I want the app to execute the same trading logic as the original script, so my trading strategy remains unchanged.**

**Acceptance Criteria:**
- EMA crossover, ATR, and VWAP filters are applied as per the script.
- Max concurrent positions, cooldowns, and daily P&L limits are enforced.
- No paper trading mode; only real trades are executed.

---

## User Story 4: Position Monitoring and Management
**As a user, I want the app to automatically monitor and manage open positions, including trailing stop-loss, targets, and EOD square-off, so I don’t need to intervene manually.**

**Acceptance Criteria:**
- Positions are updated in real-time.
- Trailing stop-loss and targets adjust dynamically.
- All positions are closed at EOD or on user interrupt.

---

## User Story 5: Security and Deployment
**As a user, I want the app to be lightweight, secure, and deployable on a single free-tier EC2 instance, so I can run it cost-effectively.**

**Acceptance Criteria:**
- Sensitive data (API keys, tokens) are never exposed in the UI or logs.
- The app runs efficiently within free-tier resource limits.
---

## User Story 6: Notifications and Alerts
**As a user, I want to receive timely notifications or alerts for key trading events (such as order execution, errors, or risk limit breaches), so I can respond quickly when needed.**

**Acceptance Criteria:**
- The app sends notifications for order executions (entry and exit).
- The app alerts the user for errors, failed trades, or API issues.
- The app notifies the user when daily profit/loss or position limits are reached.
- Notification channels may include in-app alerts, email, or push notifications (as feasible within resource constraints).
- Only authenticated users can access the dashboard and trading features.