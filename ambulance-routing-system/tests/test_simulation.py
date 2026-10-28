import networkx as nx

from simulation import (
    Ambulance,
    apply_incident,
    compare_remaining_routes,
    evaluate_incident,
    find_best_ambulance,
    shortest_route,
)


def make_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    coordinates = {
        "A": (10.0, 76.0),
        "B": (10.0, 76.01),
        "C": (10.01, 76.01),
        "D": (10.01, 76.0),
    }
    for node, (latitude, longitude) in coordinates.items():
        graph.add_node(node, lat=latitude, lon=longitude)

    def add_road(start, end, minutes, distance=1000):
        first = coordinates[start]
        second = coordinates[end]
        attrs = {
            "travel_time_min": minutes,
            "length_m": distance,
            "geometry": (first, second),
        }
        graph.add_edge(start, end, **attrs)
        graph.add_edge(
            end,
            start,
            **{**attrs, "geometry": (second, first)},
        )

    # The direct route A-B-C is faster than A-D-C until B-C is blocked.
    add_road("A", "B", 2)
    add_road("B", "C", 2)
    add_road("A", "D", 4)
    add_road("D", "C", 4)
    return graph


def test_shortest_path_returns_expected_fastest_road_route():
    graph = make_graph()
    route = shortest_route(graph, "A", "C")
    assert route is not None
    assert route.nodes == ("A", "B", "C")
    assert route.travel_time_min == 4


def test_best_ambulance_uses_road_travel_time_not_straight_line_distance():
    graph = make_graph()
    ambulances = [
        Ambulance("near-but-slow", 10.0, 76.01),
        Ambulance("farther-but-fast", 10.0, 76.0),
    ]
    # Target is C. The farther ambulance has a faster road route by construction.
    graph["B"]["C"][0]["travel_time_min"] = 10
    graph["C"]["B"][0]["travel_time_min"] = 10
    results = find_best_ambulance(
        graph,
        ambulances,
        (10.01, 76.01),
    )
    assert results
    assert results[0].ambulance.ambulance_id == "farther-but-fast"


def test_low_confidence_incident_does_not_trigger_rerouting():
    should_trigger, reason = evaluate_incident(
        confidence=0.4,
        confidence_threshold=0.6,
        confirmations=5,
        required_persistence=2,
    )
    assert should_trigger is False
    assert "below" in reason


def test_confirmed_incident_triggers_rerouting_when_alternative_exists():
    graph = make_graph()
    original = shortest_route(graph, "A", "C")
    assert original is not None
    should_trigger, _ = evaluate_incident(0.9, 0.6, 2, 2)
    assert should_trigger
    modified, _ = apply_incident(graph, ("B", "C"), severity=0.95)
    comparison = compare_remaining_routes(graph, original, 0.0, modified)
    assert comparison["adjusted_remaining"] is not None
    assert comparison["adjusted_remaining"].nodes == ("A", "D", "C")


def test_blocked_edge_is_not_used_in_alternative_route():
    graph = make_graph()
    modified, incident_type = apply_incident(graph, ("B", "C"), severity=1.0)
    route = shortest_route(modified, "A", "C")
    assert incident_type == "Road closure"
    assert route is not None
    assert ("B", "C") not in list(zip(route.nodes, route.nodes[1:]))
    assert ("C", "B") not in list(zip(route.nodes, route.nodes[1:]))


def test_incident_does_not_mutate_the_base_graph():
    graph = make_graph()
    original_weight = graph["B"]["C"][0]["travel_time_min"]
    original_edges = graph.number_of_edges()
    modified, _ = apply_incident(graph, ("B", "C"), severity=1.0)
    assert graph.number_of_edges() == original_edges
    assert graph["B"]["C"][0]["travel_time_min"] == original_weight
    assert modified.number_of_edges() < graph.number_of_edges()


def test_missing_route_is_handled_safely():
    graph = make_graph()
    graph.remove_edge("B", "C")
    graph.remove_edge("A", "B")
    graph.remove_edge("D", "C")
    graph.remove_edge("C", "D")
    assert shortest_route(graph, "A", "C") is None
    assert shortest_route(graph, "missing", "C") is None


def test_remaining_route_comparison_uses_the_same_current_node():
    graph = make_graph()
    original = shortest_route(graph, "A", "C")
    assert original is not None
    modified, _ = apply_incident(graph, ("B", "C"), severity=1.0)
    comparison = compare_remaining_routes(graph, original, 0.5, modified)
    assert comparison["current_node"] == "B"
    assert comparison["original_remaining"].start_node == "B"
    assert comparison["adjusted_remaining"].start_node == "B"
    assert comparison["original_remaining"].travel_time_min == 2
    assert comparison["adjusted_remaining"].travel_time_min == 10
