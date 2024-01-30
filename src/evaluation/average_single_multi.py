"""Parse the answers for single and multi shot to get rewards."""
import json
import re
import sys

from copy import deepcopy
from pathlib import Path
from tqdm import tqdm

import numpy as np
import pandas as pd

_category_mapper = {
    "OpenCatalyst": "OpenCatalyst",
    "BioFuels": "BioFuels",
    "RWGS": "BioFuels",
    "CO2ToEthanol": "CO2-Fuel",
    "CO2ToMethanol": "CO2-Fuel",
}


results_files = [
    Path("single_shot_results") / "single_shot_results4_rewards.json",
    Path("single_shot_results") / "single_shot_results35_rewards.json",
    Path("multi_shot_results") / "multi_shot_results35_rewards.json",
    Path("multi_shot_results") / "multi_shot_results4_rewards.json",
]

df = pd.read_csv(Path("data", "input_data", "dataset.csv"))

results = {}

df = pd.read_csv("data/input_data/dataset.csv")

max_rewards = {}
for p in results_files:
    max_rewards[p.stem] = {}
    with open(p, "r") as f:
        results = json.load(f)
    best_rewards = []
    for i, row in df.iterrows():
        print(i, row)
        dataset = row["dataset"]
        query = row["query"]
        idx = i
        rewards = []
        for sample in results.keys():
            # print(results[sample])
            # print(results[sample][query])
            if len(results[sample]) > 0 and query in results[sample]:
                rewards.append(results[sample][query]["reward"])

        if len(rewards) > 0:
            pritn(dataset)
            if dataset in max_rewards[p.stem]:
                max_rewards[p.stem][dataset].append(max(rewards))
            else:
                max_rewards[p.stem][dataset] = [max_rewards]

    print(p.stem)
    for dataset in max_rewards[p.stem].keys():
        print(f"{dataset}: {max_rewards[p.stem][dataset]}")
