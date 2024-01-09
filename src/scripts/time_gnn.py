"""A scrip to test the ammount of time for a gnn."""
import sys
import time

from pathlib import Path

sys.path.append("src")
from state.reward.simulation_reward import StructureReward  # noqa:E402

with open("gnn_timing_info.txt", "w") as f:
    sr = StructureReward(
        **{
            "llm_function": None,
            "model": "gemnet",
            "traj_dir": Path("data/output/cuda_test"),
            "device": "cpu",
            "steps": 150,
            "ads_tag": 2,
            "num_adslab_samples": 16,
        }
    )
    start = time.time()
    print(
        sr.create_structures_and_calculate(
            [["Cu"], ["Pt"], ["PtZn"]],
            ["*CO", "*O"],
            ["Cu", "Pt", "PtZn"],
            placement_type="heuristic",
        )
    )
    end = time.time()
    print(f"cuda time:\t{end-start}")
    f.write(f"cuda time:\t{end-start}")
    sr = StructureReward(
        **{
            "llm_function": None,
            "model": "gemnet",
            "traj_dir": Path("data/output/cpu_test"),
            "device": "cpu",
            "steps": 150,
            "ads_tag": 2,
            "num_adslab_samples": 16,
        }
    )
    start = time.time()
    print(
        sr.create_structures_and_calculate(
            [["Cu"], ["Pt"], ["PtZn"]],
            ["*CO", "*O"],
            ["Cu", "Pt", "PtZn"],
            placement_type="heuristic",
        )
    )
    end = time.time()
    print(f"cuda time:\t{end-start}")
    f.write(f"cuda time:\t{end-start}")
