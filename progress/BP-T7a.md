# BP-T7a — Console shell, grouped dashboards
status: done
branch: improvements/BP-T7a (no git repo in the supplied zip; changes are in the working tree)
commits: n/a
tests added: templates/blueprint/ConsoleSidebar.test.jsx (23: textOf, ROLE_LABELS, grouped + flat sidebar, crumb publishing, Session -> Log out, analytics, TabBar seam default/blueprint), components/AdminHeader.template.test.jsx (11: default markup, same controls in both templates, toolbar, onLogout publishing, both Logout controls), templates/blueprint/TitleBlockHeader.test.jsx (+6 console-variant) = 40 new; 497 total
results (default):   frontend 497 passed, 0 failed · lint 0/0 · build ok, entry gz 34,921 B
results (blueprint): frontend 497 passed, 0 failed · build ok, entry gz 35,555 B, blueprint chunk gz 10,126 B
baseline at branch cut: frontend 456 (BP-T6) · entry gz 34,925 B
gates: G1 pass (entry -4 B) · G2 pass · G3 pass (497 = 497) · G4 `data-track labels OK` · G5 lint 0/0
files:
- default files, seams only (R12 wrappers, bodies untouched): components/TabBar.jsx (`DefaultTabBar` + `TabBar` wrapper), components/AdminHeader.jsx (`DefaultAdminHeader` + wrapper; `useLastSynced` export unchanged), App.jsx (one prop: `role={bp.ROLE_LABELS[view] || ''}` on the blueprint header).
- templates/blueprint/: ConsoleSidebar.jsx (new), AdminToolbar.jsx (new), TitleBlockHeader.jsx (console variant), labels.js (+ROLE_LABELS, +textOf), index.js (exports), blueprint.css (toolbar, sidebar items, flat pill row, mobile bottom pill row, N5, N6).
decisions applied: E4 (toolbar row, no tab-name h1 in main, Logout also in the sidebar Session group), D4 (content pane = card via N6), D5 (sheet = active tab / tab count), E13 (sticky against document scroll), F7 (layout CSS-only at 768).
deviations from the card/guide:
- N5 gives `.app-column > .outer-wrap` a gutter (`0 var(--bp-gut) var(--bp-s5)`), not the guide's `padding:0`, and makes its background transparent. With 0 the org switcher, identity pill and toolbar would touch the screen edge. Scoped to dashboards so the apply page's outer-wrap (inside .bp-wrap) is untouched.
- N6 also sets `width:auto` (index.css forces 100% under 600 px).
- The console header KEEPS the Vote Now / Live Results / Apply buttons (and Back to Admin). The guide lists brand, crumb, status, sheet only, but today's nav is the only way an admin reaches the public results/apply pages from a dashboard (R3). Say if you want them removed.
- Crumb is hidden below 1024 px (header would overflow in the 769-1023 band); the sheet cell still shows the tab index.
- Group labels are `div`s with `role="group"` + aria-label, not `h3` (avoids adding headings that heading-role queries would trip over).
- The default rail's collapse-to-icons feature is not in the blueprint sidebar (the mockup has none). Its localStorage key is left alone.
- Tab icons: the default bar never rendered them either; not added.
- Mobile: grouped dashboards get the pill row pinned to the bottom of the screen (sticky, safe-area aware); flat dashboards get it at the top of the content card until T7b gives them a frame. Session -> Log out is hidden on phones (toolbar Logout is always visible).
- Sidebar analytics call (`trackPage('role:tab')`) is duplicated from DefaultTabBar (3 lines, commented) so R3 holds.
findings (not fixed):
- `TabBar` rail in default has `railCollapsed` etc. hooks; wrapper pattern means they only run in default. Nothing to do.
- `SuperAdminDashboard`/`CommissionDashboard` action buttons keep inline hex backgrounds (`#e67e22`, `#10b981`, `#f59e0b`): T8a/T8b/T9 (S2).
- Vetting's "Retry / Log out" fallback test uses `getByText('Log out')`; safe because flat dashboards get no Session item. If a grouped dashboard ever gets a test with that text, the sidebar item will collide.
not covered by jsdom (HUMAN): all groups reachable at 360 px (the pill row scrolls horizontally); rail scrolls only when taller than the viewport; Logout reachable in <= 2 interactions on every viewport; sticky header + rail offsets (header 64 + 12 margin) at 1280; bottom pill row vs the Help FAB; notched iPhone safe area under the pill row; N5/N6 card look on Super Admin and Commission in light and dark; tablet band 769-1023; mockup deep links `#p=sa`, `#p=com`.
HUMAN checks pending: the list above, with `VITE_UI_TEMPLATE=blueprint npm run dev`.
next step: BP-T7b (ConsoleFrame for the four flat dashboards: ITAdmin, FinancialController, Overseer, Vetting). Still open from T4: the vote-recorded view in App.jsx needs a seam.
