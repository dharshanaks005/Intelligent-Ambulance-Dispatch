# Intelligent Ambulance Dispatch and Routing System

A runnable, simulation-based Streamlit application for ambulance selection,
road-network routing, and incident-aware route recalculation around Thrissur,
Kerala.

## Features

- Compares at least three ambulances by estimated road travel time.
- Calculates fastest routes using NetworkX Dijkstra pathfinding.
- Displays ambulances, patient location, original route, current simulated
  position, incident location, and alternative route on an interactive Folium map.
- Simulates incident confidence, threshold, persistence, severity, and ambulance
  progress.
- Applies a road closure for high-severity incidents or a travel-time penalty for
  lower-severity incidents.
- Compares the original remaining route and adjusted route from the same current
  road-network node.
- Includes deterministic offline mode and optional OpenStreetMap road geometry.
- Includes eight deterministic tests that do not call external services.

## Architecture

```text
ambulance-routing-system/
├── app.py                  # Streamlit interface and simulation state
├── simulation.py           # Graph, dispatch, routing, and incident functions
├── requirements.txt
├── README.md
└── tests/
    └── test_simulation.py  # Offline NetworkX routing tests
```

`simulation.py` does not import Streamlit. The UI owns user controls and
`st.session_state`; the routing module owns graph processing and route math.

## Technologies

- Python
- Streamlit
- NetworkX
- Folium and streamlit-folium
- Requests for OpenStreetMap's Overpass API
- Geopy dependency for future geographic extensions
- Pytest

## Installation

From this directory:

```bash
python -m pip install -r requirements.txt
```

## Run locally or on Replit

From the repository root:

```bash
streamlit run ambulance-routing-system/app.py --server.address 0.0.0.0 --server.port 8000 --server.headless true --browser.gatherUsageStats false
```

The same command is used by the Replit workflow.

Run the routing tests from this directory:

```bash
pytest -q
```

## Using the application

1. Choose **Offline demo network** for an immediate, deterministic simulation,
   or **OpenStreetMap road data** to download roads for the Thrissur area.
2. Enter the patient's coordinates and choose which ambulances are available.
3. Select automatic dispatch or manually choose an available ambulance.
4. Use **Find Best Ambulance** to compare feasible road routes, or **Dispatch
   Ambulance** to assign the selected/best candidate.
5. Adjust ambulance progress and incident controls. Repeatedly press
   **Simulate Road Incident** to meet the persistence requirement.
6. Use **Recalculate Route** to compute a fresh route, or **Reset Simulation**
   to return to the initial state.

The first route is calculated at dispatch. A confirmed incident modifies a copy
of the base graph and triggers a new shortest-path calculation from the
simulated ambulance position.

## Routing and incident assumptions

- Ambulances are ranked only by estimated NetworkX shortest-path travel time.
  Emergency severity is displayed for context but is not part of the current
  dispatch score.
- Coordinates are snapped to nearby road nodes. The route itself follows road
  graph edge geometry; no straight line is presented as a road route.
- OpenStreetMap ways use their `maxspeed` tag when available. Otherwise,
  configurable-by-code road-class speed assumptions are used.
- Offline mode uses a deterministic synthetic grid and simulated speeds around
  Thrissur. It is not real road geometry.
- Incident confidence must meet the configured threshold, and the report must
  reach the required number of observations.
- Severity of 80% or more blocks the selected road edge in a copied graph.
  Lower severity increases that edge's travel-time weight from its original
  base value.
- The time impact is `adjusted remaining time - original remaining time`; a
  positive result is additional delay and a negative result is time saved.

## Known limitations

- No live traffic feed, accident detection, ambulance GPS, dispatch service, or
  hospital-capacity integration is included.
- OpenStreetMap data depends on external Overpass API availability and its
  usage policies. API failures are reported; the app does not silently claim
  offline roads are OSM data.
- Road travel times are estimates, not guarantees or emergency-response
  advice.
- Offline roads are intentionally simplified for academic demonstration.

## Future enhancements

- Add verified live traffic feeds and incident data sources.
- Add ambulance equipment/capacity and hospital availability to dispatch
  scoring.
- Use persistent road-network storage and a configurable service area.
- Model travel time with time-of-day and local road-class calibration.
