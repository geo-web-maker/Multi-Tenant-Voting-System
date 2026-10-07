# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.

## UI templates

The app has two complete UIs. The standard UI is the default and is unchanged when nothing is set.
The **Blueprint Console** (drawing title-block header, sidebar console, tokenised light/dark) is switched on per deployment.

| | |
|---|---|
| Switch | `VITE_UI_TEMPLATE=blueprint` (build time). Unset, empty or any other value = standard UI. Only the exact string `blueprint` activates it. |
| Change it | Set the variable (Vercel: Project → Environment Variables), then **redeploy**. Do not switch during an election window. |
| Roll back | Delete the variable (or set it empty) and redeploy. No data, backend, session or storage migration is involved. |
| Failure mode | If the blueprint chunk fails to load, the app falls back to the standard UI. |

```bash
VITE_UI_TEMPLATE=blueprint npm run dev                      # PowerShell: $env:VITE_UI_TEMPLATE='blueprint'; npm run dev
VITE_UI_TEMPLATE=blueprint npm test                         # whole suite on the blueprint markup (parity net)
bash scripts/check_template_build.sh                        # G1/G2: default build has no blueprint chunk; blueprint chunk <= 30 KB gzip
```

Rules for contributors: blueprint code lives only in `src/templates/blueprint/` and is never imported statically from
outside it (tested). New UI uses `var(--token)` colours; the hex-literal ceiling in `src/hexRatchet.test.js` may only go down.
Existing copy, `data-track`, `data-field` and ids are frozen. The official documents (results, final report, certificate)
print identically in both templates. Design source: `design/blueprint/kes-blueprint-console-mockups.html`; full spec: `BLUEPRINT_TEMPLATE_GUIDE.md`.
