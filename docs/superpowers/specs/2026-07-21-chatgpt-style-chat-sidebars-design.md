# ChatGPT-Style Chat Sidebars Design

## Goal

Make chat results consistently visible on phones by replacing the current stacked responsive grid with independently toggleable left and right sidebars inspired by ChatGPT's interaction model.

## Layout

The chat workspace has three regions:

1. A left sidebar containing the HealthyLung brand, primary navigation, signed-in user controls, new-chat action, and conversation history.
2. A center column containing a compact chat header, the message stream, and composer.
3. A right sidebar containing route diagnostics and source verification details.

The existing horizontal application top bar and mobile bottom navigation are not rendered on the chat route. Other application routes keep their current shell.

## Desktop behavior

- The left sidebar is open by default and can collapse to an icon rail.
- The collapsed rail retains the brand mark, primary navigation icons, and an expand button; history text is hidden.
- The right source sidebar opens and closes independently.
- Toggling either sidebar changes the grid columns without removing or covering the center chat stream.
- The message stream remains the only vertically scrolling chat-content region.

## Mobile behavior

- Both sidebars are closed by default.
- A compact header above the thread contains a left menu button, truncated conversation title, and a source button with the current source count.
- The menu button opens the combined navigation/history sidebar as an off-canvas overlay from the left.
- The source button opens the source sidebar as an off-canvas overlay from the right.
- Only one sidebar can be open at a time.
- Tapping the scrim, pressing Escape, selecting a navigation destination, or selecting a conversation closes the open sidebar.
- Sidebars overlay the center column and never alter its width or push chat results below the viewport.
- The mobile bottom navigation is hidden on the chat route because its destinations are present in the left sidebar.
- The layout uses dynamic viewport height so browser chrome and the fixed composer do not hide the latest response.

## Component responsibilities

- `AppShell` keeps the normal header/navigation for non-chat routes and exposes a chat-specific shell without duplicate navigation.
- `ChatWorkspace` owns sidebar open/collapsed state because it already owns conversation and source data.
- The existing history and source markup is reused in desktop sidebars and mobile drawers; no new UI dependency is added.
- Sidebar controls are native buttons with accessible labels, visible focus states, and `aria-expanded`/`aria-controls`.

## State and transitions

- Desktop left collapsed state is local UI state; persistence is not required.
- Desktop source visibility is local UI state and defaults open when sources are available.
- Opening a mobile sidebar closes the other one.
- Existing conversation selection continues to update the thread and source inspector before closing the drawer.
- CSS transitions use transform/column sizing and respect reduced-motion preferences.

## Error and edge handling

- Long conversation titles truncate rather than widening the header.
- Long navigation labels and account text truncate within the left sidebar.
- Markdown tables remain horizontally scrollable inside message bubbles.
- Mobile message bubbles use the available width and never extend behind drawer controls.
- Safe-area insets are honored around the composer and drawer bottoms.

## Verification

- Add repository/UI contract checks for chat-specific shell classes and responsive sidebar rules.
- Run TypeScript checking and the production Vite build.
- Verify at desktop, tablet, and phone viewports that the latest response is visible and scrollable.
- On mobile, verify left/right toggles, mutual exclusion, scrim close, Escape close, navigation close, and conversation-selection close.
- Verify non-chat routes retain their existing header and mobile navigation.

## Out of scope

- Pixel-for-pixel copying of ChatGPT branding or visual styling.
- Persisting sidebar preferences across sessions.
- Changing chat, Clerk, Supabase, Chroma, or source-detail data behavior.
