"""Visualise cached Notion tasks as an execution DAG."""

from __future__ import annotations

import argparse
import json
import os
import textwrap
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plot
import networkx


DEFAULT_TRACKER_STATE_PATH = Path.home() / ".notion-task-tracker" / "notion_tasks_tree.json"
DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_dag.png")
DEFAULT_DOT_OUTPUT_PATH = Path("/tmp/notion_task_dag.dot")
GRAPH_VIEW_CHOICES = ("execution-dag", "task-tree", "combined")


def main() -> None:
    arguments = _parse_arguments()
    tracker_state = _read_tracker_state(arguments.tracker_state_path)
    tasks_by_id = tracker_state["tasks"]

    task_ids_to_draw = _choose_tasks_for_requested_view(
        tasks_by_id=tasks_by_id,
        root_ticket_number=arguments.root_ticket_number,
        graph_view=arguments.graph_view,
    )
    task_graph = _derive_task_graph_for_requested_view(
        tasks_by_id=tasks_by_id,
        task_ids_to_draw=task_ids_to_draw,
        graph_view=arguments.graph_view,
    )

    _write_graphviz_dot_file(
        task_graph=task_graph,
        tasks_by_id=tasks_by_id,
        output_path=arguments.dot_output_path,
    )
    _write_matplotlib_fallback_image(
        task_graph=task_graph,
        tasks_by_id=tasks_by_id,
        output_path=arguments.output_path,
    )

    print(f"Rendered {len(task_graph.nodes)} tasks and {len(task_graph.edges)} edges.")
    print(f"Wrote Graphviz DOT to {arguments.dot_output_path}")
    print(f"Wrote fallback PNG to {arguments.output_path}")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render cached Notion tasks as an execution DAG by default.",
    )
    parser.add_argument(
        "--tracker-state-path",
        type=Path,
        default=DEFAULT_TRACKER_STATE_PATH,
        help="Cached tracker JSON path.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Fallback PNG path to write.",
    )
    parser.add_argument(
        "--dot-output-path",
        type=Path,
        default=DEFAULT_DOT_OUTPUT_PATH,
        help="Graphviz DOT path to write.",
    )
    parser.add_argument(
        "--root-ticket-number",
        type=int,
        help="Draw only this task and its descendant tasks before applying the view filter.",
    )
    parser.add_argument(
        "--graph-view",
        choices=GRAPH_VIEW_CHOICES,
        default="execution-dag",
        help="Choose dependency DAG, task tree, or combined debug graph.",
    )
    return parser.parse_args()


def _read_tracker_state(tracker_state_path: Path) -> dict[str, Any]:
    return json.loads(tracker_state_path.expanduser().read_text(encoding="utf-8"))


def _choose_tasks_for_requested_view(
    tasks_by_id: dict[str, dict[str, Any]],
    root_ticket_number: int | None,
    graph_view: str,
) -> set[str]:
    candidate_task_ids = _choose_candidate_tasks_from_cache(
        tasks_by_id=tasks_by_id,
        root_ticket_number=root_ticket_number,
    )

    if graph_view == "execution-dag":
        return _choose_leaf_tasks_from_candidates(
            tasks_by_id=tasks_by_id,
            candidate_task_ids=candidate_task_ids,
        )

    return candidate_task_ids


def _choose_candidate_tasks_from_cache(
    tasks_by_id: dict[str, dict[str, Any]],
    root_ticket_number: int | None,
) -> set[str]:
    if root_ticket_number is None:
        return set(tasks_by_id)

    return _collect_task_subtree_ids(
        tasks_by_id=tasks_by_id,
        root_task_id=_task_id_from_ticket_number(root_ticket_number),
    )


def _collect_task_subtree_ids(
    tasks_by_id: dict[str, dict[str, Any]],
    root_task_id: str,
) -> set[str]:
    task_ids_to_draw = {root_task_id}
    task_ids_waiting_for_children = [root_task_id]

    while task_ids_waiting_for_children:
        parent_task_id = task_ids_waiting_for_children.pop()
        parent_task = tasks_by_id[parent_task_id]
        for child_task_id in parent_task["child_task_ids"]:
            if child_task_id in task_ids_to_draw:
                continue
            task_ids_to_draw.add(child_task_id)
            task_ids_waiting_for_children.append(child_task_id)

    return task_ids_to_draw


def _choose_leaf_tasks_from_candidates(
    tasks_by_id: dict[str, dict[str, Any]],
    candidate_task_ids: set[str],
) -> set[str]:
    leaf_task_ids = {
        task_id
        for task_id in candidate_task_ids
        if not tasks_by_id[task_id]["child_task_ids"]
    }
    return leaf_task_ids or candidate_task_ids


def _derive_task_graph_for_requested_view(
    tasks_by_id: dict[str, dict[str, Any]],
    task_ids_to_draw: set[str],
    graph_view: str,
) -> networkx.DiGraph:
    task_graph = _create_task_graph_nodes(
        tasks_by_id=tasks_by_id,
        task_ids_to_draw=task_ids_to_draw,
    )

    if graph_view in {"task-tree", "combined"}:
        _add_parent_child_edges_to_task_graph(
            task_graph=task_graph,
            tasks_by_id=tasks_by_id,
            task_ids_to_draw=task_ids_to_draw,
        )

    if graph_view in {"execution-dag", "combined"}:
        _add_dependency_edges_to_task_graph(
            task_graph=task_graph,
            tasks_by_id=tasks_by_id,
            task_ids_to_draw=task_ids_to_draw,
        )

    _validate_task_graph_is_acyclic(task_graph)
    return task_graph


def _create_task_graph_nodes(
    tasks_by_id: dict[str, dict[str, Any]],
    task_ids_to_draw: set[str],
) -> networkx.DiGraph:
    task_graph = networkx.DiGraph()

    for task_id in sorted(task_ids_to_draw, key=_task_id_sort_key):
        task = tasks_by_id[task_id]
        task_graph.add_node(
            task_id,
            ticket_number=_ticket_number_from_task_id(task_id),
            priority=task["displayed_priority"] or task["configured_priority"],
            status=task["status"],
        )

    return task_graph


def _add_parent_child_edges_to_task_graph(
    task_graph: networkx.DiGraph,
    tasks_by_id: dict[str, dict[str, Any]],
    task_ids_to_draw: set[str],
) -> None:
    for task_id in sorted(task_ids_to_draw, key=_task_id_sort_key):
        task = tasks_by_id[task_id]
        for child_task_id in task["child_task_ids"]:
            if child_task_id in task_ids_to_draw:
                task_graph.add_edge(task_id, child_task_id, edge_kind="parent")


def _add_dependency_edges_to_task_graph(
    task_graph: networkx.DiGraph,
    tasks_by_id: dict[str, dict[str, Any]],
    task_ids_to_draw: set[str],
) -> None:
    for task_id in sorted(task_ids_to_draw, key=_task_id_sort_key):
        task = tasks_by_id[task_id]
        for dependency_task_id in task["dependency_task_ids"]:
            if dependency_task_id in task_ids_to_draw:
                task_graph.add_edge(dependency_task_id, task_id, edge_kind="dependency")


def _validate_task_graph_is_acyclic(task_graph: networkx.DiGraph) -> None:
    if networkx.is_directed_acyclic_graph(task_graph):
        return

    cycle = networkx.find_cycle(task_graph)
    raise ValueError(f"Task graph contains a cycle: {cycle}")


def _write_graphviz_dot_file(
    task_graph: networkx.DiGraph,
    tasks_by_id: dict[str, dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(_graphviz_dot_lines(task_graph=task_graph, tasks_by_id=tasks_by_id)),
        encoding="utf-8",
    )


def _graphviz_dot_lines(
    task_graph: networkx.DiGraph,
    tasks_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    lines = [
        "digraph notion_task_dag {",
        '  graph [rankdir=LR, overlap=false, splines=true];',
        '  node [shape=box, style="rounded,filled", fillcolor="#dbeafe", color="#1f2937", fontname="Helvetica"];',
        '  edge [fontname="Helvetica", color="#2563eb"];',
    ]

    for task_id in sorted(task_graph.nodes, key=_task_id_sort_key):
        lines.append(
            f'  "{_ticket_number_from_task_id(task_id)}" [label="{_graphviz_label_for_task(task_id=task_id, task=tasks_by_id[task_id])}"];'
        )

    for source_task_id, target_task_id, edge in task_graph.edges(data=True):
        lines.append(
            f'  "{_ticket_number_from_task_id(source_task_id)}" -> "{_ticket_number_from_task_id(target_task_id)}" [{_graphviz_attributes_for_edge(edge)}];'
        )

    lines.append("}")
    return lines


def _write_matplotlib_fallback_image(
    task_graph: networkx.DiGraph,
    tasks_by_id: dict[str, dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    task_positions = _position_tasks_by_dag_generation(task_graph)
    figure, axes = plot.subplots(
        figsize=(
            _figure_width_for_task_positions(task_positions),
            _figure_height_for_task_positions(task_positions),
        ),
        constrained_layout=True,
    )

    parent_edges = _edges_matching_kind(task_graph, "parent")
    dependency_edges = _edges_matching_kind(task_graph, "dependency")
    task_labels = {
        task_id: _matplotlib_label_for_task(task_id=task_id, task=tasks_by_id[task_id])
        for task_id in task_graph.nodes
    }

    networkx.draw_networkx_edges(
        task_graph,
        task_positions,
        edgelist=parent_edges,
        arrows=True,
        arrowstyle="-|>",
        arrowsize=14,
        edge_color="#64748b",
        width=1.3,
        ax=axes,
    )
    networkx.draw_networkx_edges(
        task_graph,
        task_positions,
        edgelist=dependency_edges,
        arrows=True,
        arrowstyle="-|>",
        arrowsize=20,
        edge_color="#2563eb",
        width=2.4,
        connectionstyle="arc3,rad=0.08",
        ax=axes,
    )
    networkx.draw_networkx_labels(
        task_graph,
        task_positions,
        labels=task_labels,
        font_size=7,
        font_family="sans-serif",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "#dbeafe",
            "edgecolor": "#1f2937",
            "linewidth": 1.0,
        },
        ax=axes,
    )

    axes.set_title("Notion task DAG", fontsize=15)
    _set_plot_bounds_from_task_positions(axes, task_positions)
    axes.axis("off")
    figure.savefig(output_path, dpi=180)
    plot.close(figure)


def _edges_matching_kind(task_graph: networkx.DiGraph, edge_kind: str) -> list[tuple[str, str]]:
    return [
        (source_task_id, target_task_id)
        for source_task_id, target_task_id, edge in task_graph.edges(data=True)
        if edge["edge_kind"] == edge_kind
    ]


def _position_tasks_by_dag_generation(task_graph: networkx.DiGraph) -> dict[str, tuple[float, float]]:
    if not task_graph.nodes:
        return {}

    task_generations = list(networkx.topological_generations(task_graph))
    task_positions = {}

    for generation_index, task_generation in enumerate(task_generations):
        ordered_task_ids = sorted(task_generation, key=_task_id_sort_key)
        vertical_offset = (len(ordered_task_ids) - 1) / 2
        for task_index, task_id in enumerate(ordered_task_ids):
            task_positions[task_id] = (generation_index, vertical_offset - task_index)

    return task_positions


def _figure_width_for_task_positions(task_positions: dict[str, tuple[float, float]]) -> float:
    generation_count = len({x_position for x_position, _ in task_positions.values()})
    return max(12, generation_count * 3.6)


def _figure_height_for_task_positions(task_positions: dict[str, tuple[float, float]]) -> float:
    tasks_in_tallest_generation = max(
        (
            sum(1 for position in task_positions.values() if position[0] == generation_index)
            for generation_index in {x_position for x_position, _ in task_positions.values()}
        ),
        default=1,
    )
    return max(8, tasks_in_tallest_generation * 1.1)


def _set_plot_bounds_from_task_positions(axes, task_positions: dict[str, tuple[float, float]]) -> None:
    x_positions = [position[0] for position in task_positions.values()]
    y_positions = [position[1] for position in task_positions.values()]
    axes.set_xlim(min(x_positions, default=0) - 0.6, max(x_positions, default=0) + 0.6)
    axes.set_ylim(min(y_positions, default=0) - 0.8, max(y_positions, default=0) + 0.8)


def _graphviz_label_for_task(task_id: str, task: dict[str, Any]) -> str:
    return _escape_graphviz_label(
        f"{_ticket_number_from_task_id(task_id)} | {task['displayed_priority'] or task['configured_priority']} | {task['status']}\n"
        f"{textwrap.fill(task['title'], width=32)}"
    )


def _matplotlib_label_for_task(task_id: str, task: dict[str, Any]) -> str:
    task_summary = f"{_ticket_number_from_task_id(task_id)} | {task['displayed_priority'] or task['configured_priority']} | {task['status']}"
    wrapped_title = textwrap.fill(task["title"], width=24)
    return f"{task_summary}\n{wrapped_title}"


def _graphviz_attributes_for_edge(edge: dict[str, str]) -> str:
    if edge["edge_kind"] == "dependency":
        return 'label="depends", color="#2563eb", penwidth=2.2'

    return 'label="child", color="#64748b"'


def _escape_graphviz_label(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _task_id_from_ticket_number(ticket_number: int) -> str:
    return f"ALOVYA-{ticket_number}"


def _ticket_number_from_task_id(task_id: str) -> str:
    return task_id.removeprefix("ALOVYA-")


def _task_id_sort_key(task_id: str) -> tuple[str, int, str]:
    task_prefix, separator, task_number_text = task_id.rpartition("-")

    if separator and task_number_text.isdigit():
        return task_prefix, int(task_number_text), ""

    return task_id, -1, task_id


if __name__ == "__main__":
    main()
