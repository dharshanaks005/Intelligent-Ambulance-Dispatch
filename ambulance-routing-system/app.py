from __future__ import annotations

from datetime import datetime
from typing import Any

import folium
import streamlit as st
from streamlit_folium import st_folium

from simulation import (
    DEFAULT_AMBULANCES,
    THRISSUR_CENTER,
    Ambulance,
    Route,
    apply_incident,
    build_offline_demo_graph,
    build_overpass_graph,
    compare_remaining_routes,
    edge_at_progress,
    evaluate_incident,
    find_best_ambulance,
    graph_to_payload,
    incident_edge_coordinate,
    route_between_coordinates,
)

st.set_page_config(
    page_title="Intelligent Ambulance Dispatch",
    page_icon="🚑",
    layout="wide",
)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def get_overpass_payload(
    radius_km: float = 12,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Cache OSM results by radius; never cache mutable graph state."""
    try:
        return (
            True,
            graph_to_payload(build_overpass_graph(radius_km=radius_km)),
            None,
        )
    except Exception as exc:  # external service errors should not crash the dashboard
        return False, None, str(exc)


def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "widget_version": 0,
        "event_log": [],
        "dispatch_candidates": [],
        "selected_ambulance_id": None,
        "original_route": None,
        "incident_result": None,
        "incident_edge": None,
        "incident_active": False,
        "incident_confirmations": 0,
        "simulation_status": "Ready",
        "dispatch_mode": "Automatic best response time",
        "last_input_signature": None,
        "last_incident_enabled": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def log_event(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.event_log.insert(0, f"{timestamp} — {message}")
    st.session_state.event_log = st.session_state.event_log[:30]


def clear_results(status: str = "Ready") -> None:
    st.session_state.dispatch_candidates = []
    st.session_state.selected_ambulance_id = None
    st.session_state.original_route = None
    st.session_state.incident_result = None
    st.session_state.incident_edge = None
    st.session_state.incident_active = False
    st.session_state.incident_confirmations = 0
    st.session_state.simulation_status = status


def prepare_dispatch(
    graph: Any,
    patient: tuple[float, float],
    available_ids: set[str],
    selection_mode: str,
    manual_ambulance_id: str | None,
) -> bool:
    candidates = find_best_ambulance(
        graph,
        DEFAULT_AMBULANCES,
        patient,
        available_ids=available_ids,
    )
    if not candidates:
        st.session_state.simulation_status = "No feasible ambulance"
        log_event("Dispatch could not be completed: no available ambulance has a feasible road route.")
        return False
    selected = candidates[0]
    if selection_mode == "Choose an ambulance":
        selected = next(
            (
                candidate
                for candidate in candidates
                if candidate.ambulance.ambulance_id == manual_ambulance_id
            ),
            None,
        )
        if selected is None:
            st.error("The selected ambulance is not available or has no feasible route.")
            return False
    st.session_state.dispatch_candidates = candidates
    st.session_state.selected_ambulance_id = selected.ambulance.ambulance_id
    st.session_state.original_route = selected.route
    st.session_state.incident_result = None
    st.session_state.incident_edge = None
    st.session_state.incident_active = False
    st.session_state.incident_confirmations = 0
    st.session_state.simulation_status = (
        "Ambulance dispatched"
        if selection_mode == "Choose an ambulance"
        else "Best ambulance identified"
    )
    log_event(
        f"{selected.ambulance.ambulance_id} selected using estimated road travel time "
        f"({selected.route.travel_time_min:.1f} min)."
    )
    log_event(
        f"Original road route calculated: {selected.route.distance_km:.2f} km, "
        f"{selected.route.travel_time_min:.1f} min."
    )
    return True


def get_selected_ambulance() -> Ambulance | None:
    ambulance_id = st.session_state.selected_ambulance_id
    return next(
        (
            ambulance
            for ambulance in DEFAULT_AMBULANCES
            if ambulance.ambulance_id == ambulance_id
        ),
        None,
    )


def run_incident(
    graph: Any,
    progress: float,
    severity: float,
    confidence: float,
    threshold: float,
    required_persistence: int,
    *,
    count_confirmation: bool,
) -> None:
    route: Route | None = st.session_state.original_route
    if route is None:
        st.error("Find or dispatch an ambulance before simulating a road incident.")
        return
    if count_confirmation:
        st.session_state.incident_confirmations += 1
        log_event(
            f"Road incident observation received "
            f"({st.session_state.incident_confirmations}/{required_persistence} persistence confirmations)."
        )
    try:
        triggered, reason = evaluate_incident(
            confidence,
            threshold,
            st.session_state.incident_confirmations,
            required_persistence,
        )
        comparison = compare_remaining_routes(graph, route, progress)
        route_edges = list(zip(route.nodes, route.nodes[1:]))
        existing_edge = st.session_state.incident_edge
        if existing_edge not in route_edges and (
            existing_edge is None or (existing_edge[1], existing_edge[0]) not in route_edges
        ):
            existing_edge = None
        incident_edge = existing_edge or edge_at_progress(route, progress)
        modified_graph = None
        incident_type = "Not applied"
        if triggered:
            modified_graph, incident_type = apply_incident(
                graph, incident_edge, severity
            )
            comparison = compare_remaining_routes(
                graph, route, progress, modified_graph
            )
            st.session_state.incident_edge = incident_edge
            st.session_state.incident_active = True
            if comparison["adjusted_remaining"] is None:
                st.session_state.simulation_status = "No alternative route"
                log_event(
                    "Incident confirmed, but no feasible alternative road route exists."
                )
            else:
                st.session_state.simulation_status = "Route recalculated"
                log_event(
                    f"Incident confirmed ({incident_type.lower()}); an alternative route was calculated."
                )
        else:
            st.session_state.incident_edge = incident_edge
            st.session_state.incident_active = False
            st.session_state.simulation_status = "Original route retained"
            log_event(f"Rerouting not triggered: {reason}")
        st.session_state.incident_result = {
            "triggered": triggered,
            "reason": reason,
            "incident_type": incident_type,
            "severity": severity,
            "confidence": confidence,
            "comparison": comparison,
        }
        log_event(
            "Remaining travel-time comparison uses the same simulated position for both routes."
        )
    except (ValueError, KeyError) as exc:
        st.error(f"Unable to simulate the incident: {exc}")
        st.session_state.simulation_status = "Incident simulation unavailable"


def map_for_simulation(
    graph: Any,
    patient: tuple[float, float],
    available_ids: set[str],
    progress: float,
) -> folium.Map:
    selected_ambulance = get_selected_ambulance()
    if selected_ambulance:
        map_center = (
            (selected_ambulance.latitude + patient[0]) / 2,
            (selected_ambulance.longitude + patient[1]) / 2,
        )
    else:
        map_center = patient
    map_object = folium.Map(
        location=map_center,
        zoom_start=13,
        control_scale=True,
        tiles="OpenStreetMap",
    )

    for ambulance in DEFAULT_AMBULANCES:
        available = ambulance.ambulance_id in available_ids
        selected = ambulance.ambulance_id == st.session_state.selected_ambulance_id
        label = (
            f"{ambulance.ambulance_id} — "
            f"{'selected, responding' if selected else 'available' if available else 'unavailable'}"
        )
        folium.Marker(
            location=ambulance.coordinate,
            tooltip=label,
            icon=folium.Icon(
                color="blue" if selected else "green" if available else "gray",
                icon="plus-sign",
                prefix="glyphicon",
            ),
        ).add_to(map_object)

    folium.Marker(
        location=patient,
        tooltip="Patient location",
        icon=folium.Icon(color="red", icon="flag", prefix="glyphicon"),
    ).add_to(map_object)

    route: Route | None = st.session_state.original_route
    if route and len(route.coordinates) > 1:
        folium.PolyLine(
            route.coordinates,
            color="#2677d8",
            weight=6,
            opacity=0.8,
            tooltip="Original fastest road route",
        ).add_to(map_object)
        result = st.session_state.incident_result
        if result is None:
            comparison = compare_remaining_routes(graph, route, progress)
            triggered = False
        else:
            comparison = result["comparison"]
            triggered = result["triggered"]
        if comparison:
            alternative: Route | None = comparison["adjusted_remaining"]
            if (
                triggered
                and alternative
                and len(alternative.coordinates) > 1
            ):
                folium.PolyLine(
                    alternative.coordinates,
                    color="#0d9871",
                    weight=6,
                    opacity=0.9,
                    tooltip="Incident-adjusted route from current position",
                ).add_to(map_object)
            current_position = comparison.get("current_position")
            if current_position:
                folium.CircleMarker(
                    location=current_position,
                    radius=7,
                    color="#102a43",
                    fill=True,
                    fill_color="#ffffff",
                    fill_opacity=1,
                    tooltip="Ambulance current simulated position",
                ).add_to(map_object)
        if st.session_state.incident_edge:
            incident_location = incident_edge_coordinate(
                graph, st.session_state.incident_edge
            )
            folium.Marker(
                location=incident_location,
                tooltip=(
                    "Confirmed simulated road incident"
                    if st.session_state.incident_active
                    else "Reported, unconfirmed simulated incident"
                ),
                icon=folium.Icon(
                    color="orange" if st.session_state.incident_active else "lightgray",
                    icon="warning-sign",
                    prefix="glyphicon",
                ),
            ).add_to(map_object)
    return map_object


initialize_state()
st.title("Intelligent Ambulance Dispatch and Routing System")
st.caption(
    "Simulation-based intelligent emergency dispatch and dynamic road rerouting."
)
st.info(
    "Academic simulation only. OpenStreetMap provides road geometry; travel speeds, "
    "incident reports, and traffic conditions are estimated or simulated."
)

widget_version = st.session_state.widget_version
with st.sidebar:
    st.header("Simulation Controls")
    network_source = st.radio(
        "Road network",
        ("Offline demo network", "OpenStreetMap road data"),
        index=0,
        help="Offline roads are deterministic simulated data. OpenStreetMap downloads real road geometry when available.",
        key="network_source",
    )
    st.subheader("Patient details")
    patient_lat = st.number_input(
        "Patient latitude",
        min_value=-90.0,
        max_value=90.0,
        value=THRISSUR_CENTER[0],
        format="%.6f",
        help="Latitude of the simulated emergency.",
        key=f"patient_lat_{widget_version}",
    )
    patient_lon = st.number_input(
        "Patient longitude",
        min_value=-180.0,
        max_value=180.0,
        value=THRISSUR_CENTER[1],
        format="%.6f",
        help="Longitude of the simulated emergency.",
        key=f"patient_lon_{widget_version}",
    )
    emergency_severity = st.slider(
        "Emergency severity",
        min_value=1,
        max_value=5,
        value=3,
        help="Context for the simulation log; dispatch ranking currently uses road response time only.",
    )
    emergency_description = st.text_input(
        "Emergency description",
        placeholder="Optional short note",
    )

    st.subheader("Ambulance settings")
    ambulance_ids = [ambulance.ambulance_id for ambulance in DEFAULT_AMBULANCES]
    available_ids = set(
        st.multiselect(
            "Available ambulances",
            options=ambulance_ids,
            default=ambulance_ids,
            help="Only these units are considered for dispatch.",
            key=f"available_ambulances_{widget_version}",
        )
    )
    selection_mode = st.selectbox(
        "Ambulance selection",
        ("Automatic best response time", "Choose an ambulance"),
        help="Automatic mode chooses the feasible unit with the lowest road travel time.",
    )
    manual_ambulance_id = None
    if selection_mode == "Choose an ambulance":
        manual_ambulance_id = st.selectbox(
            "Select ambulance",
            options=ambulance_ids,
        )
    progress = st.slider(
        "Ambulance progress along route",
        min_value=0,
        max_value=100,
        value=0,
        help="Simulates how far the ambulance has travelled before an incident is evaluated.",
    ) / 100

    st.subheader("Road incident")
    incident_enabled = st.toggle(
        "Incident active",
        value=True,
        help="When disabled, incident simulation retains the original route.",
    )
    incident_severity = st.slider(
        "Incident severity",
        min_value=0,
        max_value=100,
        value=90,
        help="Severity at or above 80% blocks the affected road; lower values add a travel-time penalty.",
    ) / 100
    incident_confidence = st.slider(
        "Incident confidence",
        min_value=0,
        max_value=100,
        value=90,
        help="Confidence in the simulated incident report.",
    ) / 100
    confidence_threshold = st.slider(
        "Confidence threshold",
        min_value=0,
        max_value=100,
        value=65,
        help="Incident confidence must meet this threshold before rerouting.",
    ) / 100
    persistence = st.slider(
        "Required incident persistence",
        min_value=1,
        max_value=5,
        value=2,
        help="Number of incident observations required before rerouting.",
    )

    find_button = st.button("Find Best Ambulance", width="stretch")
    dispatch_button = st.button("Dispatch Ambulance", width="stretch")
    run_button = st.button("Run Simulation", width="stretch")
    incident_button = st.button("Simulate Road Incident", width="stretch")
    recalculate_button = st.button("Recalculate Route", width="stretch")
    reset_button = st.button("Reset Simulation", width="stretch")
    retry_osm_button = False
    if network_source == "OpenStreetMap road data":
        network_radius = st.slider(
            "OpenStreetMap area radius (km)",
            min_value=2,
            max_value=25,
            value=12,
            help="Download roads within this approximate radius of central Thrissur.",
        )
        retry_osm_button = st.button(
            "Retry OpenStreetMap download", width="stretch"
        )
    else:
        network_radius = None

    if reset_button:
        clear_results()
        st.session_state.event_log = []
        st.session_state.last_input_signature = None
        st.session_state.widget_version += 1
        log_event("Simulation reset to the initial state.")
        st.rerun()

    if retry_osm_button:
        get_overpass_payload.clear()

patient = (float(patient_lat), float(patient_lon))
input_signature = (
    network_source,
    network_radius,
    patient,
    tuple(sorted(available_ids)),
    selection_mode,
    manual_ambulance_id,
)
if (
    st.session_state.last_input_signature is not None
    and st.session_state.last_input_signature != input_signature
):
    clear_results("Inputs changed — recalculate dispatch.")
    log_event("Dispatch results cleared because patient, ambulance, or network inputs changed.")
st.session_state.last_input_signature = input_signature

if st.session_state.last_incident_enabled is None:
    st.session_state.last_incident_enabled = incident_enabled
elif st.session_state.last_incident_enabled != incident_enabled:
    if not incident_enabled:
        st.session_state.incident_result = None
        st.session_state.incident_edge = None
        st.session_state.incident_active = False
        st.session_state.incident_confirmations = 0
        st.session_state.simulation_status = "Incident deactivated — original route restored"
        log_event("Incident deactivated; the original road graph and route are restored.")
    else:
        log_event("Incident activation enabled.")
    st.session_state.last_incident_enabled = incident_enabled

graph = None
network_label = ""
if network_source == "Offline demo network":
    graph = build_offline_demo_graph()
    network_label = "Offline demonstration graph — simulated roads and speeds"
else:
    with st.spinner("Loading OpenStreetMap road data for the Thrissur area..."):
        osm_ok, osm_payload, osm_error = get_overpass_payload(
            float(network_radius)
        )
    if osm_ok and osm_payload:
        from simulation import graph_from_payload

        graph = graph_from_payload(osm_payload)
        network_label = "OpenStreetMap road geometry — estimated travel times, no live traffic"
    else:
        st.error(
            "OpenStreetMap road data could not be loaded. "
            f"The offline demo remains available by selecting it in Simulation Controls. Details: {osm_error}"
        )
        st.caption(
            "The app has not silently substituted simulated roads for OpenStreetMap data."
        )

if network_label:
    st.caption(f"Road source: {network_label}")

if graph is not None:
    if find_button:
        prepare_dispatch(
            graph,
            patient,
            available_ids,
            "Automatic best response time",
            None,
        )
    if dispatch_button:
        prepare_dispatch(
            graph, patient, available_ids, selection_mode, manual_ambulance_id
        )
        if st.session_state.selected_ambulance_id:
            st.session_state.simulation_status = "Ambulance responding"
            log_event(
                f"{st.session_state.selected_ambulance_id} dispatched to the patient location."
            )
    if run_button:
        if st.session_state.original_route is None:
            ready = prepare_dispatch(
                graph, patient, available_ids, selection_mode, manual_ambulance_id
            )
        else:
            ready = True
        if ready:
            if incident_enabled:
                run_incident(
                    graph,
                    progress,
                    incident_severity,
                    incident_confidence,
                    confidence_threshold,
                    persistence,
                    count_confirmation=True,
                )
                log_event("Simulation run completed.")
            else:
                st.session_state.simulation_status = "Route active — incident disabled"
                log_event("Simulation run completed with incident handling disabled.")
    if incident_button:
        if st.session_state.original_route is None:
            prepared = prepare_dispatch(
                graph, patient, available_ids, selection_mode, manual_ambulance_id
            )
        else:
            prepared = True
        if prepared:
            if incident_enabled:
                run_incident(
                    graph,
                    progress,
                    incident_severity,
                    incident_confidence,
                    confidence_threshold,
                    persistence,
                    count_confirmation=True,
                )
            else:
                log_event("Incident was not applied because incident activation is disabled.")
                st.session_state.simulation_status = "Incident disabled"
    if recalculate_button:
        ambulance = get_selected_ambulance()
        if ambulance is None:
            prepared = prepare_dispatch(
                graph, patient, available_ids, selection_mode, manual_ambulance_id
            )
        else:
            try:
                route = route_between_coordinates(graph, ambulance.coordinate, patient)
                if route is None:
                    st.error("No feasible road route exists for the selected ambulance.")
                    prepared = False
                else:
                    st.session_state.original_route = route
                    st.session_state.incident_result = None
                    st.session_state.incident_edge = None
                    st.session_state.incident_active = False
                    st.session_state.incident_confirmations = 0
                    st.session_state.simulation_status = "Route recalculated"
                    log_event(
                        f"Route recalculated for {ambulance.ambulance_id}: "
                        f"{route.distance_km:.2f} km, {route.travel_time_min:.1f} min."
                    )
                    prepared = True
            except ValueError as exc:
                st.error(f"Unable to recalculate the route: {exc}")
                prepared = False
        if prepared and incident_enabled and st.session_state.incident_confirmations:
            run_incident(
                graph,
                progress,
                incident_severity,
                incident_confidence,
                confidence_threshold,
                persistence,
                count_confirmation=False,
            )

    st.subheader("Dispatch overview")
    candidates = st.session_state.dispatch_candidates
    selected_id = st.session_state.selected_ambulance_id
    selected_candidate = next(
        (
            candidate
            for candidate in candidates
            if candidate.ambulance.ambulance_id == selected_id
        ),
        None,
    )
    incident_result = st.session_state.incident_result
    comparison = None
    if st.session_state.original_route is not None:
        modified_graph = None
        if (
            incident_result
            and incident_result["triggered"]
            and st.session_state.incident_edge
        ):
            modified_graph, _ = apply_incident(
                graph,
                st.session_state.incident_edge,
                incident_result["severity"],
            )
        comparison = compare_remaining_routes(
            graph,
            st.session_state.original_route,
            progress,
            modified_graph,
        )
        if incident_result is not None:
            incident_result = {**incident_result, "comparison": comparison}
            st.session_state.incident_result = incident_result
    original_remaining: Route | None = None
    adjusted_remaining: Route | None = None
    if comparison:
        original_remaining = comparison["original_remaining"]
        adjusted_remaining = comparison["adjusted_remaining"]

    metric_cols = st.columns(6)
    metric_cols[0].metric("Selected ambulance", selected_id or "—")
    metric_cols[1].metric(
        "Original trip",
        f"{selected_candidate.route.travel_time_min:.1f} min"
        if selected_candidate
        else "—",
    )
    metric_cols[2].metric(
        "Original remaining",
        f"{original_remaining.travel_time_min:.1f} min"
        if original_remaining
        else "—",
    )
    metric_cols[3].metric(
        "Adjusted remaining",
        f"{adjusted_remaining.travel_time_min:.1f} min"
        if adjusted_remaining
        else "—",
    )
    metric_cols[4].metric(
        "Route distance",
        f"{selected_candidate.route.distance_km:.2f} km"
        if selected_candidate
        else "—",
    )
    time_delta = None
    if original_remaining and adjusted_remaining:
        time_delta = adjusted_remaining.travel_time_min - original_remaining.travel_time_min
    impact = "—"
    if time_delta is not None:
        impact = f"{time_delta:+.1f} min"
    metric_cols[5].metric("Time impact", impact)
    st.caption(f"Simulation status: **{st.session_state.simulation_status}**")
    if emergency_description:
        st.caption(
            f"Emergency severity {emergency_severity}/5 — {emergency_description}"
        )

    left, right = st.columns([1.7, 1])
    with left:
        st.subheader("Interactive road map")
        map_object = map_for_simulation(graph, patient, available_ids, progress)
        st_folium(map_object, height=540, use_container_width=True, returned_objects=[])
        st.caption(
            "Blue: original road route. Green: incident-adjusted route. "
            "Red: patient. Orange: confirmed incident. "
            "The current ambulance position is a white-centered marker."
        )
    with right:
        st.subheader("Candidate comparison")
        if candidates:
            candidate_rows = [
                {
                    "Rank": rank,
                    "Ambulance": candidate.ambulance.ambulance_id,
                    "Road distance (km)": round(candidate.route.distance_km, 2),
                    "Estimated time (min)": round(candidate.route.travel_time_min, 1),
                    "Selected": "Yes"
                    if candidate.ambulance.ambulance_id == selected_id
                    else "No",
                }
                for rank, candidate in enumerate(candidates, start=1)
            ]
            st.dataframe(candidate_rows, hide_index=True, width="stretch")
        else:
            st.info("Find or dispatch an ambulance to calculate road-route candidates.")

        st.subheader("Route comparison")
        if comparison:
            original = comparison["original_remaining"]
            adjusted = comparison["adjusted_remaining"]
            incident_triggered = bool(
                incident_result and incident_result["triggered"]
            )
            status_text = (
                incident_result["incident_type"]
                if incident_triggered
                else "Not evaluated"
                if incident_result is None
                else "Not applied"
            )
            rows = [
                {
                    "Metric": "Estimated remaining travel time",
                    "Original route": f"{original.travel_time_min:.1f} min",
                    "Adjusted route": f"{adjusted.travel_time_min:.1f} min"
                    if adjusted
                    else "No feasible route"
                    if incident_triggered
                    else "Not recalculated",
                },
                {
                    "Metric": "Remaining route distance",
                    "Original route": f"{original.distance_km:.2f} km",
                    "Adjusted route": f"{adjusted.distance_km:.2f} km"
                    if adjusted
                    else "Unavailable"
                    if incident_triggered
                    else "Not recalculated",
                },
                {
                    "Metric": "Incident effect",
                    "Original route": "No modification",
                    "Adjusted route": status_text,
                },
                {
                    "Metric": "Route status",
                    "Original route": "Baseline",
                    "Adjusted route": "Alternative"
                    if incident_triggered and adjusted
                    else "No feasible alternative"
                    if incident_triggered
                    else "Not evaluated"
                    if incident_result is None
                    else "Original retained",
                },
            ]
            st.table(rows)
            if incident_result:
                st.caption(incident_result["reason"])
            else:
                st.caption("Run the simulation to evaluate an incident.")
        else:
            st.info("Route comparison appears after a route is calculated.")

        st.subheader("Simulation log")
        if st.session_state.event_log:
            for event in st.session_state.event_log:
                st.markdown(f"- {event}")
        else:
            st.caption("No simulation events yet.")

st.divider()
with st.expander("How the simulation works and its limitations"):
    st.markdown(
        """
        - **Dispatch:** eligible ambulances are ranked by Dijkstra shortest-path travel time on the road graph. Straight-line distance is used only for snapping coordinates to nearby road nodes.
        - **OpenStreetMap mode:** road geometry is downloaded from Overpass. Missing speed limits use road-class speed assumptions; this is not live traffic data.
        - **Offline demo mode:** a deterministic synthetic grid near Thrissur is used and is explicitly labelled as simulated.
        - **Incident confirmation:** rerouting requires both confidence at or above the threshold and enough incident observations to meet persistence.
        - **Incident effect:** severity of 80% or more closes the selected road edge; lower severity applies a delay calculated from the original edge weight.
        - **Travel-time comparison:** the original route's remaining suffix and the adjusted route both start at the same simulated road node. Time impact is adjusted remaining time minus original remaining time.
        - **Limitations:** ambulance positions, speeds, traffic, incident confidence, and persistence are simulation inputs; there is no live dispatch, GPS tracking, accident detection, or traffic feed.
        """
    )
