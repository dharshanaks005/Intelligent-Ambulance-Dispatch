"""Reusable road-routing and incident simulation logic.

The graph model is independent of Streamlit so it can be tested with small,
deterministic NetworkX graphs.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Hashable, Iterable, Mapping, Sequence

import networkx as nx

Coordinate = tuple[float, float]  # latitude, longitude
NodeId = Hashable

THRISSUR_CENTER: Coordinate = (10.5276, 76.2144)
BLOCK_SEVERITY_THRESHOLD = 0.8


@dataclass(frozen=True)
class Ambulance:
    ambulance_id: str
    latitude: float
    longitude: float
    status: str = "available"

    @property
    def coordinate(self) -> Coordinate:
        return (self.latitude, self.longitude)


@dataclass(frozen=True)
class Route:
    nodes: tuple[NodeId, ...]
    coordinates: tuple[Coordinate, ...]
    distance_km: float
    travel_time_min: float

    @property
    def start_node(self) -> NodeId:
        return self.nodes[0]

    @property
    def end_node(self) -> NodeId:
        return self.nodes[-1]


@dataclass(frozen=True)
class DispatchCandidate:
    ambulance: Ambulance
    route: Route


DEFAULT_AMBULANCES: tuple[Ambulance, ...] = (
    Ambulance("AMB-101", 10.5276, 76.1984),
    Ambulance("AMB-204", 10.5156, 76.2144),
    Ambulance("AMB-317", 10.5396, 76.2304),
)


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Raise ValueError when a geographic coordinate is outside valid bounds."""
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees.")


def haversine_km(first: Coordinate, second: Coordinate) -> float:
    """Return great-circle distance between two (latitude, longitude) points."""
    lat1, lon1 = first
    lat2, lon2 = second
    validate_coordinates(lat1, lon1)
    validate_coordinates(lat2, lon2)
    earth_radius_km = 6371.0088
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    value = (
        sin(delta_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_km * atan2(sqrt(value), sqrt(max(0.0, 1 - value)))


def _edge_items(graph: nx.Graph, source: NodeId, target: NodeId) -> list[dict[str, Any]]:
    if not graph.has_edge(source, target):
        return []
    edge_data = graph.get_edge_data(source, target)
    if graph.is_multigraph():
        return list(edge_data.values())
    return [edge_data]


def _best_edge_data(
    graph: nx.Graph, source: NodeId, target: NodeId
) -> dict[str, Any] | None:
    items = _edge_items(graph, source, target)
    if not items:
        return None
    return min(items, key=lambda item: float(item.get("travel_time_min", 0.0)))


def _node_coordinate(graph: nx.Graph, node: NodeId) -> Coordinate:
    attributes = graph.nodes[node]
    if "lat" in attributes and "lon" in attributes:
        return (float(attributes["lat"]), float(attributes["lon"]))
    if "y" in attributes and "x" in attributes:
        return (float(attributes["y"]), float(attributes["x"]))
    raise ValueError(f"Road node {node!r} has no latitude/longitude coordinates.")


def nearest_node(
    graph: nx.Graph,
    coordinate: Coordinate,
    *,
    max_distance_km: float = 15.0,
) -> NodeId:
    """Snap a coordinate to its nearest graph node, rejecting distant snaps."""
    validate_coordinates(*coordinate)
    if graph.number_of_nodes() == 0:
        raise ValueError("The road network contains no nodes.")
    closest_node: NodeId | None = None
    closest_distance = float("inf")
    for node in graph.nodes:
        distance = haversine_km(coordinate, _node_coordinate(graph, node))
        if distance < closest_distance:
            closest_node, closest_distance = node, distance
    if closest_node is None or closest_distance > max_distance_km:
        raise ValueError(
            f"No road node is within {max_distance_km:g} km of the selected location."
        )
    return closest_node


def shortest_route(graph: nx.Graph, origin: NodeId, destination: NodeId) -> Route | None:
    """Calculate a fastest route using edge travel-time weights.

    Returns None when either node is absent or no path exists.
    """
    if origin not in graph or destination not in graph:
        return None
    try:
        path = nx.shortest_path(
            graph,
            source=origin,
            target=destination,
            weight="travel_time_min",
            method="dijkstra",
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return route_from_nodes(graph, path)


def route_from_nodes(graph: nx.Graph, nodes: Sequence[NodeId]) -> Route | None:
    """Summarize a specified graph path, preserving the selected road geometries."""
    if not nodes:
        return None
    if any(node not in graph for node in nodes):
        return None
    distance_m = 0.0
    travel_time_min = 0.0
    coordinates: list[Coordinate] = []
    if len(nodes) == 1:
        coordinates.append(_node_coordinate(graph, nodes[0]))
    for source, target in zip(nodes, nodes[1:]):
        edge = _best_edge_data(graph, source, target)
        if edge is None:
            return None
        start_coordinate = _node_coordinate(graph, source)
        end_coordinate = _node_coordinate(graph, target)
        geometry = edge.get("geometry")
        if geometry:
            segment = [(float(lat), float(lon)) for lat, lon in geometry]
        else:
            segment = [start_coordinate, end_coordinate]
        if coordinates and segment and coordinates[-1] == segment[0]:
            coordinates.extend(segment[1:])
        else:
            coordinates.extend(segment)
        distance_m += float(
            edge.get("length_m", haversine_km(start_coordinate, end_coordinate) * 1000)
        )
        travel_time_min += float(edge.get("travel_time_min", 0.0))
    return Route(
        nodes=tuple(nodes),
        coordinates=tuple(coordinates),
        distance_km=distance_m / 1000,
        travel_time_min=travel_time_min,
    )


def route_between_coordinates(
    graph: nx.Graph,
    origin: Coordinate,
    destination: Coordinate,
    *,
    max_snap_distance_km: float = 15.0,
) -> Route | None:
    """Route between map coordinates after snapping them to road nodes."""
    validate_coordinates(*origin)
    validate_coordinates(*destination)
    try:
        origin_node = nearest_node(
            graph, origin, max_distance_km=max_snap_distance_km
        )
        destination_node = nearest_node(
            graph, destination, max_distance_km=max_snap_distance_km
        )
    except ValueError:
        raise
    return shortest_route(graph, origin_node, destination_node)


def find_best_ambulance(
    graph: nx.Graph,
    ambulances: Iterable[Ambulance],
    patient: Coordinate,
    *,
    available_ids: set[str] | None = None,
) -> list[DispatchCandidate]:
    """Rank feasible ambulances by calculated road travel time."""
    validate_coordinates(*patient)
    candidates: list[DispatchCandidate] = []
    for ambulance in ambulances:
        if ambulance.status.lower() != "available":
            continue
        if available_ids is not None and ambulance.ambulance_id not in available_ids:
            continue
        try:
            route = route_between_coordinates(graph, ambulance.coordinate, patient)
        except ValueError:
            continue
        if route is not None:
            candidates.append(DispatchCandidate(ambulance=ambulance, route=route))
    return sorted(candidates, key=lambda candidate: candidate.route.travel_time_min)


def evaluate_incident(
    confidence: float,
    confidence_threshold: float,
    confirmations: int,
    required_persistence: int,
) -> tuple[bool, str]:
    """Decide whether a reported incident is sufficiently confirmed."""
    for name, value in (
        ("confidence", confidence),
        ("confidence threshold", confidence_threshold),
    ):
        if not 0 <= value <= 1:
            raise ValueError(f"{name.capitalize()} must be between 0 and 1.")
    if required_persistence < 1 or confirmations < 0:
        raise ValueError("Persistence must be positive and confirmations cannot be negative.")
    if confidence < confidence_threshold:
        return False, "Confidence is below the configured threshold."
    if confirmations < required_persistence:
        return (
            False,
            f"Incident is not persistent yet ({confirmations}/{required_persistence} confirmations).",
        )
    return True, "Incident confidence and persistence requirements are met."


def edge_at_progress(route: Route, progress: float) -> tuple[NodeId, NodeId]:
    """Choose the route edge at the ambulance's current simulated progress."""
    if not 0 <= progress <= 1:
        raise ValueError("Progress must be between 0 and 1.")
    if len(route.nodes) < 2:
        raise ValueError("A route needs at least two nodes to place an incident.")
    index = min(int(progress * (len(route.nodes) - 1)), len(route.nodes) - 2)
    return route.nodes[index], route.nodes[index + 1]


def apply_incident(
    base_graph: nx.Graph,
    edge: tuple[NodeId, NodeId],
    severity: float,
    *,
    block_threshold: float = BLOCK_SEVERITY_THRESHOLD,
) -> tuple[nx.Graph, str]:
    """Return a modified copy of the base graph with a delay or road closure.

    Repeated calls always calculate penalties from the unmodified base graph.
    """
    if not 0 <= severity <= 1:
        raise ValueError("Incident severity must be between 0 and 1.")
    source, target = edge
    forward = _edge_items(base_graph, source, target)
    reverse = _edge_items(base_graph, target, source)
    if not forward and not reverse:
        raise ValueError("The incident edge does not exist in the road network.")
    modified = base_graph.copy()
    if severity >= block_threshold:
        if modified.is_multigraph():
            for u, v in ((source, target), (target, source)):
                if modified.has_edge(u, v):
                    for key in list(modified[u][v]):
                        modified.remove_edge(u, v, key)
        else:
            if modified.has_edge(source, target):
                modified.remove_edge(source, target)
            if modified.has_edge(target, source):
                modified.remove_edge(target, source)
        return modified, "Road closure"

    multiplier = 1 + (4 * severity)
    for u, v in ((source, target), (target, source)):
        if not modified.has_edge(u, v):
            continue
        if modified.is_multigraph():
            for key, attributes in modified[u][v].items():
                base_attributes = base_graph[u][v][key]
                attributes["travel_time_min"] = (
                    float(base_attributes["travel_time_min"]) * multiplier
                )
        else:
            modified[u][v]["travel_time_min"] = (
                float(base_graph[u][v]["travel_time_min"]) * multiplier
            )
    return modified, "Traffic slowdown"


def compare_remaining_routes(
    base_graph: nx.Graph,
    original_route: Route,
    progress: float,
    modified_graph: nx.Graph | None = None,
) -> dict[str, Any]:
    """Compare route times from the same simulated position to the destination.

    The original estimate uses the remaining suffix of the selected route. The
    adjusted estimate is newly optimized from the exact same current graph node.
    """
    if not 0 <= progress <= 1:
        raise ValueError("Progress must be between 0 and 1.")
    path_index = min(
        int(progress * (len(original_route.nodes) - 1)),
        len(original_route.nodes) - 1,
    )
    current_node = original_route.nodes[path_index]
    destination = original_route.end_node
    original_remaining = route_from_nodes(
        base_graph, original_route.nodes[path_index:]
    )
    if original_remaining is None:
        raise ValueError("The original route is no longer available in the base graph.")
    adjusted_remaining = None
    if modified_graph is not None:
        adjusted_remaining = shortest_route(
            modified_graph, current_node, destination
        )
    return {
        "current_node": current_node,
        "current_position": _node_coordinate(base_graph, current_node),
        "original_remaining": original_remaining,
        "adjusted_remaining": adjusted_remaining,
    }


def build_offline_demo_graph(center: Coordinate = THRISSUR_CENTER) -> nx.MultiDiGraph:
    """Build a deterministic grid of simulated roads near Thrissur."""
    validate_coordinates(*center)
    graph = nx.MultiDiGraph()
    rows, columns = 5, 5
    lat_step, lon_step = 0.006, 0.008
    for row in range(rows):
        for column in range(columns):
            node = row * columns + column
            latitude = center[0] + (row - 2) * lat_step
            longitude = center[1] + (column - 2) * lon_step
            graph.add_node(node, lat=latitude, lon=longitude)

    def add_road(source: int, target: int, speed_kph: float) -> None:
        first = _node_coordinate(graph, source)
        second = _node_coordinate(graph, target)
        length_m = haversine_km(first, second) * 1000
        travel_time_min = (length_m / 1000) / speed_kph * 60
        attributes = {
            "length_m": length_m,
            "travel_time_min": travel_time_min,
            "speed_kph": speed_kph,
            "geometry": (first, second),
        }
        graph.add_edge(source, target, **attributes)
        graph.add_edge(
            target,
            source,
            **{**attributes, "geometry": (second, first)},
        )

    for row in range(rows):
        for column in range(columns - 1):
            speed = 32 if row in (1, 3) else 24
            add_road(row * columns + column, row * columns + column + 1, speed)
    for row in range(rows - 1):
        for column in range(columns):
            speed = 30 if column in (1, 3) else 22
            add_road(row * columns + column, (row + 1) * columns + column, speed)
    return graph


def graph_to_payload(graph: nx.Graph) -> dict[str, Any]:
    """Convert a graph to a cache-safe, serializable representation."""
    nodes = [(node, dict(attributes)) for node, attributes in graph.nodes(data=True)]
    edges: list[tuple[NodeId, NodeId, Any, dict[str, Any]]] = []
    if graph.is_multigraph():
        for source, target, key, attributes in graph.edges(keys=True, data=True):
            edges.append((source, target, key, dict(attributes)))
    else:
        for source, target, attributes in graph.edges(data=True):
            edges.append((source, target, None, dict(attributes)))
    return {
        "directed": graph.is_directed(),
        "multigraph": graph.is_multigraph(),
        "nodes": nodes,
        "edges": edges,
    }


def graph_from_payload(payload: Mapping[str, Any]) -> nx.Graph:
    """Rebuild a fresh mutable graph from a cached payload."""
    if payload["multigraph"]:
        graph: nx.Graph = nx.MultiDiGraph() if payload["directed"] else nx.MultiGraph()
    else:
        graph = nx.DiGraph() if payload["directed"] else nx.Graph()
    graph.add_nodes_from((node, dict(attributes)) for node, attributes in payload["nodes"])
    for source, target, key, attributes in payload["edges"]:
        if graph.is_multigraph():
            graph.add_edge(source, target, key=key, **dict(attributes))
        else:
            graph.add_edge(source, target, **dict(attributes))
    return graph


def parse_maxspeed(value: Any, highway: str) -> float:
    """Parse common OSM maxspeed values or use a documented road-class estimate."""
    defaults = {
        "motorway": 80,
        "trunk": 65,
        "primary": 45,
        "secondary": 35,
        "tertiary": 30,
        "residential": 25,
        "unclassified": 25,
        "service": 15,
    }
    if value:
        raw_value = str(value).split(";")[0].strip().lower()
        number = ""
        for character in raw_value:
            if character.isdigit() or character == ".":
                number += character
            elif number:
                break
        if number:
            speed = float(number)
            if "mph" in raw_value:
                speed *= 1.60934
            if speed > 0:
                return speed
    return float(defaults.get(highway, 25))


def build_overpass_graph(
    center: Coordinate = THRISSUR_CENTER,
    radius_km: float = 12,
    *,
    timeout_seconds: int = 35,
) -> nx.MultiDiGraph:
    """Download and convert a drivable OSM road network using Overpass."""
    import requests

    validate_coordinates(*center)
    if not 1 <= radius_km <= 50:
        raise ValueError("Road network radius must be between 1 and 50 km.")
    latitude_delta = radius_km / 111.0
    longitude_delta = radius_km / max(1.0, 111.0 * cos(radians(center[0])))
    south = center[0] - latitude_delta
    north = center[0] + latitude_delta
    west = center[1] - longitude_delta
    east = center[1] + longitude_delta
    query = f"""
    [out:json][timeout:{timeout_seconds}];
    way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service)$"]
      ({south},{west},{north},{east});
    (._;>;);
    out body;
    """
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers={"User-Agent": "AmbulanceDispatchSimulation/1.0 (academic demo)"},
        timeout=timeout_seconds + 5,
    )
    response.raise_for_status()
    payload = response.json()
    elements = payload.get("elements", [])
    node_coordinates = {
        element["id"]: (float(element["lat"]), float(element["lon"]))
        for element in elements
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    graph = nx.MultiDiGraph()
    for node_id, (latitude, longitude) in node_coordinates.items():
        graph.add_node(node_id, lat=latitude, lon=longitude)
    for way in (item for item in elements if item.get("type") == "way"):
        tags = way.get("tags", {})
        highway_value = tags.get("highway", "residential")
        highway = (
            highway_value[0]
            if isinstance(highway_value, list)
            else str(highway_value)
        )
        speed_kph = parse_maxspeed(tags.get("maxspeed"), highway)
        oneway = str(tags.get("oneway", "")).lower()
        way_nodes = way.get("nodes", [])
        for first_id, second_id in zip(way_nodes, way_nodes[1:]):
            if first_id not in node_coordinates or second_id not in node_coordinates:
                continue
            first = node_coordinates[first_id]
            second = node_coordinates[second_id]
            length_m = haversine_km(first, second) * 1000
            travel_time_min = (length_m / 1000) / max(speed_kph, 5) * 60
            attributes = {
                "length_m": length_m,
                "travel_time_min": travel_time_min,
                "speed_kph": speed_kph,
                "highway": highway,
                "geometry": (first, second),
            }
            if oneway in {"-1", "reverse"}:
                graph.add_edge(second_id, first_id, **{**attributes, "geometry": (second, first)})
            else:
                graph.add_edge(first_id, second_id, **attributes)
                if oneway not in {"yes", "1", "true"}:
                    graph.add_edge(
                        second_id,
                        first_id,
                        **{**attributes, "geometry": (second, first)},
                    )
    graph.remove_nodes_from(list(nx.isolates(graph)))
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise ValueError("OpenStreetMap returned an empty road network for this area.")
    return graph


def incident_edge_coordinate(
    graph: nx.Graph, edge: tuple[NodeId, NodeId]
) -> Coordinate:
    """Return a map coordinate near the center of a simulated road incident."""
    first = _node_coordinate(graph, edge[0])
    second = _node_coordinate(graph, edge[1])
    return ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
