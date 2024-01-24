import json
import shutil
import sys

from pathlib import Path

from ase import Atoms
from ase.io import read

import matplotlib.pyplot as plt
import numpy as np

import networkx as nx

sys.path.append("src")
from search.state.reasoner_state import ReasonerState
from evaluation.pickle_to_raw import bfs_to_nx  # noqa:402

def _clean_list(data: list):
    new_data = data.copy()
    for i, v in enumerate(data):
        if isinstance(v, np.ndarray):
            new_data[i] = list(v)
        elif isinstance(v, dict):
            new_data[i] = _clean_json(v)
        elif isinstance(v, list):
            new_data[i] = _clean_list(v)
        else:
            new_data[i] = v
    return new_data


def _clean_json(data: dict):
    new_data = data.copy()
    for k, v in data.items():
        if k in [
            "embeddings",
            "embedding_model",
            "reward_adjustment_value",
            "reward_adjusted_similarities",
            "similarities",
            "reward",
        ]:
            del new_data[k]
        elif isinstance(v, np.ndarray):
            new_data[k] = list(v)
        elif isinstance(v, dict):
            new_data[k] = _clean_json(v)
        elif isinstance(v, list):
            new_data[k] = _clean_list(v)
        else:
            new_data[k] = v
    return new_data

if __name__ == "__main__":

    for i in range(145):
        fname = Path(f"icml/search_tree_{i}.json")
        if Path(fname).exists():
            with open(
                fname,
                "r",
                ) as f:
                data = json.load(f)
            #print(len(data["node_rewards"]))

            for i in range(len(data["nodes"])):
                for j in range(len(data["nodes"][i])):
                    reasoner_state = ReasonerState.from_dict(data["nodes"][i][j])
                    data["nodes"][i][j].update(
                        {
                            "generation_prompt": reasoner_state.generation_prompt,
                            "generation_system_prompt": reasoner_state.generation_system_prompt,
                        }
                    )
            for i in range(len(data["generated_nodes"])):
                for j in range(len(data["generated_nodes"][i])):
                    reasoner_state = ReasonerState.from_dict(data["generated_nodes"][i][j])
                    data["generated_nodes"][i][j].update(
                        {
                            "generation_prompt": reasoner_state.generation_prompt,
                            "generation_system_prompt": reasoner_state.generation_system_prompt,
                        }
                    )

            T = bfs_to_nx(data)

            DT = nx.DiGraph()
            DT.add_nodes_from(T.nodes(data=True))
            DT.add_edges_from(T.edges(data=True))

            j_graph = nx.json_graph.tree_data(DT, root=0)
            #print(list(j_graph["children"][0].keys()))
            j_graph = _clean_json(j_graph)
            #print(list(j_graph["children"][0].keys()))

            flattened_node_rewards = [r for r_list in data["node_rewards"] for r in r_list]

            if len(data["node_rewards"]) == 6 and not np.allclose(flattened_node_rewards, -10):

                with open(Path("icml_processed") / (fname.stem + ".json"), "w") as f:
                    json.dump(j_graph, f)
            else:
                print(f"Skipping {fname}. Tree depth: {len(data['node_rewards'])}, allclose: {np.allclose(flattened_node_rewards, -10)}")

            import matplotlib.pyplot as plt
            import networkx as nx
            import pydot
            from networkx.drawing.nx_pydot import graphviz_layout
        else:
            print(f"Skipping {fname}. Doesn't exist.")

    for i in range(145):
        fname = Path(f"icml/reasoner_policy/search_tree_{i}.json")
        if Path(fname).exists():
            with open(
                fname,
                "r",
                ) as f:
                data = json.load(f)
            #print(len(data["node_rewards"]))

            for i in range(len(data["nodes"])):
                for j in range(len(data["nodes"][i])):
                    reasoner_state = ReasonerState.from_dict(data["nodes"][i][j])
                    data["nodes"][i][j].update(
                        {
                            "generation_prompt": reasoner_state.generation_prompt,
                            "generation_system_prompt": reasoner_state.generation_system_prompt,
                        }
                    )
            for i in range(len(data["generated_nodes"])):
                for j in range(len(data["generated_nodes"][i])):
                    reasoner_state = ReasonerState.from_dict(data["generated_nodes"][i][j])
                    data["generated_nodes"][i][j].update(
                        {
                            "generation_prompt": reasoner_state.generation_prompt,
                            "generation_system_prompt": reasoner_state.generation_system_prompt,
                        }
                    )

            T = bfs_to_nx(data)

            DT = nx.DiGraph()
            DT.add_nodes_from(T.nodes(data=True))
            DT.add_edges_from(T.edges(data=True))

            j_graph = nx.json_graph.tree_data(DT, root=0)
            #print(list(j_graph["children"][0].keys()))
            j_graph = _clean_json(j_graph)
            #print(list(j_graph["children"][0].keys()))

            flattened_node_rewards = [r for r_list in data["node_rewards"] for r in r_list]

            if len(data["node_rewards"]) == 6 and not np.allclose(flattened_node_rewards, -10):

                with open(Path("icml_processed", "reasoner_policy") / (fname.stem + ".json"), "w") as f:
                    json.dump(j_graph, f)
            else:
                print(f"Skipping {fname}. Tree depth: {len(data['node_rewards'])}, allclose: {np.allclose(flattened_node_rewards, -10)}")

            import matplotlib.pyplot as plt
            import networkx as nx
            import pydot
            from networkx.drawing.nx_pydot import graphviz_layout
        else:
            print(f"Skipping {fname}. Doesn't exist.")

