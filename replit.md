# Intelligent Ambulance Dispatch and Routing System

Simulation-based Streamlit app for comparing ambulance response times, routing on road graphs, and recalculating routes after simulated incidents.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `streamlit run ambulance-routing-system/app.py --server.address 0.0.0.0 --server.port 8000 --server.headless true --browser.gatherUsageStats false` — run the ambulance dispatch app
- `python -m pytest -q ambulance-routing-system/tests` — run deterministic routing tests
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9, Python 3.13
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Ambulance simulation: Streamlit, NetworkX, Folium, and OpenStreetMap Overpass

## Where things live

- `ambulance-routing-system/app.py` — Streamlit dashboard, map, controls, and session state
- `ambulance-routing-system/simulation.py` — reusable graph routing, dispatch, and incident engine
- `ambulance-routing-system/tests/` — offline deterministic routing tests
- `ambulance-routing-system/README.md` — setup, algorithm assumptions, and limitations
- `lib/api-spec/openapi.yaml` — API contract source of truth
- `lib/db/src/schema/` — database schema

## Architecture decisions

- Ambulance ranking uses estimated road travel time; straight-line distance is used only to snap locations to road nodes.
- Incident changes are applied to a copied graph so the base network remains unchanged.
- Offline demo roads are explicitly simulated; OpenStreetMap road geometry does not provide live traffic or incident detection.

## Product

The Streamlit dashboard simulates ambulance dispatch around Thrissur, compares feasible road routes, and visualizes incident-aware rerouting. It includes deterministic offline roads and optional OpenStreetMap road data.

## User preferences

- Keep Streamlit as the primary user interface for the ambulance dispatch project.

## Gotchas

- Run `python -m pytest -q ambulance-routing-system/tests` from the workspace root for the deterministic routing suite.
- OpenStreetMap mode depends on the public Overpass API; offline mode remains usable without external road data.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
