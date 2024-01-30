"""Parse the answers for single and multi shot to get rewards."""
import json
import re
import sys

from copy import deepcopy
from pathlib import Path
from tqdm import tqdm

import pandas as pd

from ase.data import chemical_symbols

sys.path.append("src")
from datasets import reasoner_data_loader  # noqa:E402
from search.reward import simulation_reward  # noqa:E402

results_files = [
    Path("single_shot_results") / "single_shot_results4.json",
    Path("single_shot_results") / "single_shot_results35.json",
    Path("multi_shot_results") / "multi_shot_results35.json",
    Path("multi_shot_results") / "multi_shot_results4.json",
]

df = pd.read_csv(Path("data", "input_data", "dataset.csv"))

results = {}

sr = simulation_reward.StructureReward()

for p in results_files:
    results[p.stem] = {}
    with open(p, "r") as f:
        data = json.load(f)
    for sample in tqdm(sorted(data.keys())):
        results[sample] = {}
        for query, syms in tqdm(sorted(data[sample].items(), key=lambda x: x[0])):
            processed_syms = [s.replace("-", "").replace("/", "") for s in syms]
            processed_syms = [re.findall("[A-Z][^A-Z]*", s) for s in processed_syms]
            if not all(
                [s in chemical_symbols for s_list in processed_syms for s in s_list]
            ):
                print([s for s_list in processed_syms for s in s_list])

            dataset = df.iloc[int(query)]["dataset"]
            query = df.iloc[int(query)]["query"]
            state = reasoner_data_loader.get_state(
                dataset, query, chain_of_thought=True
            )

            (
                adslabs_and_energies,
                gnn_calls,
                gnn_time,
                name_candidate_mapping,
            ) = sr.create_structures_and_calculate(
                processed_syms,
                state.ads_symbols,
                ["".join(s_list) for s_list in processed_syms],
            )

            if state.ads_preferences is not None:
                final_reward, reward_values = sr.parse_adsorption_energies(
                    state,
                    adslabs_and_energies,
                    name_candidate_mapping,
                    ["".join(s_list) for s_list in processed_syms],
                    state.ads_preferences,
                )
            else:
                (
                    final_reward,
                    reward_values,
                    adsorption_energies,
                ) = sr.parse_adsorption_pathways(
                    adslabs_and_energies,
                    name_candidate_mapping,
                    ["".join(s_list) for s_list in processed_syms],
                    state.reaction_pathways,
                )

            if "simulation-reward" in state.info.keys():
                state.info["simulation-reward"].update(
                    {
                        "slab_syms": processed_syms,
                        "value": final_reward,
                        "reward_values": deepcopy(reward_values),
                        "gnn_calls": gnn_calls,
                        "gnn_time": gnn_time,
                    }
                )
            else:
                state.info["simulation-reward"] = {
                    "slab_syms": processed_syms,
                    "value": final_reward,
                    "reward_values": deepcopy(reward_values),
                    "gnn_calls": gnn_calls,
                    "gnn_time": gnn_time,
                }
            if state.ads_preferences is None:
                state.info["simulation-reward"].update(
                    {"intermediate_energies": adsorption_energies}
                )
            results[sample][query] = {"reward": final_reward, "tmp_state": vars(state)}

    with open(p.parent / (p.stem + "_rewards.json"), "r") as f:
        data = json.load(f)
