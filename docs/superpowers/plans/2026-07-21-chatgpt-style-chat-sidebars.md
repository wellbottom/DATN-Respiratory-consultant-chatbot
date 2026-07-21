# ChatGPT-Style Chat Sidebars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep chat results visible on phones by combining navigation/history into a toggleable left sidebar and making sources an independently toggleable right sidebar.

**Architecture:** `AppShell` suppresses its horizontal chrome only on `/chat`; `ChatWorkspace` owns the two sidebar states because it already owns conversation and source data. CSS uses inline grid columns on desktop and transform-based off-canvas drawers on mobile, leaving the center thread as the only chat viewport.

**Tech Stack:** React 19, React Router, TypeScript, CSS media queries, existing Lucide icons, Vite.

## Global Constraints

- Add no dependency.
- Reuse current history, source, navigation, and drawer behavior.
- Mobile sidebars overlay the chat and never push it below the viewport.
- Only one mobile sidebar may be open at a time.
- Non-chat routes retain their current header and mobile navigation.
- Controls require accessible labels, focus states, `aria-expanded`, and `aria-controls`.

---

### Task 1: Make the application shell chat-aware

**Files:**
- Modify: `web_app/frontend/src/components/AppShell.tsx`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: `location.pathname` from React Router.
- Produces: `.app-container.chat-route` with no duplicate top bar or bottom navigation on `/chat`.

- [ ] **Step 1: Write a failing shell contract test**

Add assertions that `AppShell.tsx` defines `isChatRoute`, applies `chat-route`, and conditionally renders both `top-bar` and `mobile-nav` only outside chat.

- [ ] **Step 2: Run the test and confirm RED**

Run: `python -m unittest tests.test_repository_contract.RepositoryContractTests.test_chat_route_owns_its_navigation -v`

Expected: FAIL because `isChatRoute` is absent.

- [ ] **Step 3: Implement the minimal route-aware shell**

Use this structure without changing non-chat navigation:

```tsx
const isChatRoute = currentPath === "/chat";

return (
  <div className={`app-container ${isChatRoute ? "chat-route" : ""}`}>
    {!isChatRoute && <header className="top-bar">...</header>}
    <main className="main-content">{children}</main>
    {!isChatRoute && <nav className="mobile-nav">...</nav>}
  </div>
);
```

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_repository_contract -v && npm run lint --prefix web_app/frontend`

Commit: `git commit -am "feat: make app shell chat-aware"`

### Task 2: Add independent left and right sidebar controls

**Files:**
- Modify: `web_app/frontend/src/views/ChatWorkspace.tsx`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: current conversation/source state and `navigate()`.
- Produces: `isLeftSidebarOpen`, `isLeftSidebarCollapsed`, and `isRightSidebarOpen` behavior plus accessible toggle buttons.

- [ ] **Step 1: Write failing interaction-contract assertions**

Require named left/right state, mutual-exclusion open handlers, `aria-expanded`, `aria-controls`, scrim close, and Escape close code in `ChatWorkspace.tsx`.

- [ ] **Step 2: Run the test and confirm RED**

Run: `python -m unittest tests.test_repository_contract.RepositoryContractTests.test_chat_has_accessible_sidebar_toggles -v`

Expected: FAIL because the new state and controls are absent.

- [ ] **Step 3: Implement minimal state and handlers**

```tsx
const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(false);
const [isLeftSidebarCollapsed, setIsLeftSidebarCollapsed] = useState(false);
const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(true);

const openLeftSidebar = () => {
  setIsRightSidebarOpen(false);
  setIsLeftSidebarOpen(true);
};
const openRightSidebar = () => {
  setIsLeftSidebarOpen(false);
  setIsRightSidebarOpen(true);
};
```

Move the existing app destinations into the left sidebar above new chat/history. Add desktop collapse controls and mobile overlay controls. Close the mobile sidebar after navigation or conversation selection. Add one Escape listener that closes both overlays.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_repository_contract -v && npm run lint --prefix web_app/frontend`

Commit: `git commit -am "feat: add toggleable chat sidebars"`

### Task 3: Implement responsive inline and off-canvas layout

**Files:**
- Modify: `web_app/frontend/src/index.css`
- Modify: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: `.left-sidebar-open`, `.left-sidebar-collapsed`, `.right-sidebar-open`, and `.chat-route` classes.
- Produces: desktop grid columns and phone overlay drawers using `100dvh`.

- [ ] **Step 1: Write failing responsive CSS contract assertions**

Require `100dvh`, mobile sidebar transforms, hidden closed sidebars, full-width mobile bubbles, safe-area composer padding, and reduced-motion handling.

- [ ] **Step 2: Run the test and confirm RED**

Run: `python -m unittest tests.test_repository_contract.RepositoryContractTests.test_chat_sidebars_have_mobile_overlay_css -v`

Expected: FAIL because those responsive rules are absent.

- [ ] **Step 3: Add the minimum CSS**

Desktop uses grid columns `280px minmax(0, 1fr) 340px`, collapsed left rail `72px`, and closed right column `0`. At `max-width: 900px`, both sidebars are fixed overlays, closed with `translateX(±100%)`, opened with `translateX(0)`, and the workspace is `calc(100dvh - env(safe-area-inset-bottom))`. Set mobile bubble width to `100%`, compact thread/composer padding, and honor `prefers-reduced-motion`.

- [ ] **Step 4: Run automated verification**

Run:

```text
python -m unittest discover -s tests -v
npm run lint --prefix web_app/frontend
npm run build --prefix web_app/frontend
```

Expected: all commands exit 0.

- [ ] **Step 5: Verify in browser**

At 390×844 verify left/right open, mutual exclusion, scrim/Escape close, visible latest response, composer above safe area, and no bottom navigation. At 1280×800 verify left collapse and independent source toggle. Verify `/`, `/community`, and `/find-care` retain existing shell.

- [ ] **Step 6: Commit**

Commit: `git commit -am "fix: make chat sidebars responsive"`
