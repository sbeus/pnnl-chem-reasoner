"""Module for reward funciton by calculation of adsorption energies in simulation."""
import json
import math
import sys

from functools import reduce
from pathlib import Path

import numpy as np

from ase import Atoms
from ase.data import chemical_symbols

sys.path.append("src")
from llm import query, ase_interface  # noqa: E402
from nnp import oc  # noqa: E402
from search.reward.base_reward import BaseReward  # noqa: E402


class StructureReward(BaseReward):
    """Calculate the reward for answers based on adsorption simulations."""

    def __init__(self, nnp_class="oc", **nnp_kwargs):
        """Select the class of nnp for the reward function."""
        if nnp_class == "oc":
            self.adsorption_calculator = oc.OCAdsorptionCalculator(**nnp_kwargs)
        else:
            raise NotImplementedError(f"No such nnp class {nnp_class}.")

    def __call__(self, s: query.QueryState):
        """Return the calculated adsorption energy from the predicted catalysts."""
        candidates_list = s.candidates
        ads_list = s.ads_symbols
        slab_syms = (
            candidates_list  # ase_interface.llm_answer_to_symbols(candidates_list)
        )
        slabs = []
        for syms in slab_syms:
            if syms is not None:
                struct = ase_interface.symbols_list_to_bulk(syms)
            else:
                struct = syms
            slabs.append(struct)
        ads = [
            ase_interface.ads_symbols_to_structure(ads_syms) for ads_syms in ads_list
        ]

        adslab_combinations = []
        for i, s in enumerate(slabs):
            for j, a in enumerate(ads):
                adslab_combinations.append((candidates_list[i], s, ads_list[j], a))

        adslab_ats = []  # List to store initial adslabs and indices
        name_candidate_mapping = (
            {}
        )  # dictionary to get from database names to candidates
        for combo in adslab_combinations:
            if combo[1] is not None:
                s = combo[1]
                a = combo[3]
                name = f"{self.reduce_metal_symbols(s)}_{combo[2]}"
                adslab_ats += self.sample_adslabs(s, a, name)
                name_candidate_mapping[name] = combo[0]
        adslabs_and_energies = self.create_batches_and_calculate(
            adslab_ats,
        )
        # Pase our the rewards into candidate/adsorbate
        reward_values = {}
        for idx, name, energy in adslabs_and_energies:
            cand = name_candidate_mapping[name]
            ads = name.split("_")[-1]
            return
            if cand in reward_values.keys():
                if name.split("_")[-1] in reward_values[cand].keys():
                    reward_values[cand][ads] += [energy]
                else:
                    reward_values[cand][ads] = [energy]
            else:
                reward_values[cand] = {ads: [energy]}

        # aggregate the rewards
        rewards = []
        for cand in candidates_list:
            if cand in reward_values.keys():
                rewards.append(
                    np.mean(
                        [
                            abs(min(reward_values[cand][ads])) ** s.ads_preferences[i]
                            for i, ads in enumerate(reward_values[cand].keys())
                        ]
                    )
                )
            else:  # Handle default here TODO: determine some logic/pentaly for this
                pass
        final_reward = np.mean(rewards)
        s.reward = final_reward
        return final_reward  # return mean over candidates

    def create_batches_and_calculate(self, adslabs):
        """Split adslabs into batches and run the simulations."""
        results = []
        adslab_batch = []
        fname_batch = []
        for idx, name, adslab in adslabs:

            fname = Path(f"{name}") / f"{idx}"
            (self.adsorption_calculator.traj_dir / fname).parent.mkdir(
                parents=True, exist_ok=True
            )
            if not (
                self.adsorption_calculator.traj_dir / (str(fname) + ".traj")
            ).exists():
                adslab_batch.append(adslab)
                fname_batch.append(str(fname))
            else:
                idx = str(fname.stem)
                name = str(fname.parent)
                if (
                    self.adsorption_calculator.traj_dir / name / "adsorption.json"
                ).exists():
                    with open(
                        self.adsorption_calculator.traj_dir / name / "adsorption.json",
                        "r",
                    ) as f:
                        data = json.load(f)
                        if (
                            idx in data.keys()
                            and "adsorption_energy" in data[idx].keys()
                        ):
                            ads_energy = data[idx]["adsorption_energy"]
                            results.append((idx, name, ads_energy))
                        else:
                            adslab_batch.append(adslab)
                            fname_batch.append(str(fname))
                else:
                    adslab_batch.append(adslab)
                    fname_batch.append(str(fname))

            if len(adslab_batch) == self.adsorption_calculator.batch_size:
                batch_results = self.calculate_batch(adslab_batch, fname_batch)
                results += self.unpack_batch_results(batch_results, fname_batch)
                adslab_batch = []
                fname_batch = []

        if len(adslab_batch) > 0:
            batch_results = self.calculate_batch(adslab_batch, fname_batch)
            results += self.unpack_batch_results(batch_results, fname_batch)
            adslab_batch = []
            fname_batch = []

        return results

    @staticmethod
    def unpack_batch_results(batch_results, fname_batch):
        """Unpack a collection of batch results."""
        results = []
        for i, res in enumerate(batch_results):
            idx = Path(fname_batch[i]).stem
            name = str(Path(fname_batch[i]).parent)
            results.append((idx, name, res))
        return results

    def calculate_batch(self, adslab_batch, fname_batch):
        """Calculate adsorption energies for a batch of atoms objects."""
        batch_relaxed = self.adsorption_calculator.batched_relax_atoms(
            adslab_batch, fname_batch
        )
        batch_adsorption_energies = (
            self.adsorption_calculator.batched_adsorption_calculation(
                batch_relaxed, fname_batch
            )
        )
        return batch_adsorption_energies

    @staticmethod
    def sample_adslabs(slab, ads, name, num_samples=8):
        """Sample possible adsorbate+slab combinations."""
        adslabs = []
        for i in range(num_samples):
            adslab = ase_interface.combine_adsorbate_slab(slab, ads)
            adslabs.append((i, name, adslab))
        return adslabs

    @staticmethod
    def reduce_metal_symbols(metal_ats: Atoms):
        """Reduce the symbols of metal symbols to a basic form."""
        numbers = metal_ats.get_atomic_numbers()
        syms_count = {}
        for num in numbers:
            sym = chemical_symbols[num]
            if sym in syms_count.keys():
                syms_count[sym] += 1
            else:
                syms_count[sym] = 1
        gcd = reduce(math.gcd, list(syms_count.values()))
        formula = ""
        for s, count in sorted(syms_count.items(), key=lambda item: item[0]):
            formula += f"{s}{count//gcd}"
        return formula


class _TestState:
    def __init__(self, test_candidates, test_ads_symbols, test_ads_preferences):
        """Create test query state for testing the reward function."""
        self.candidates = test_candidates
        self.ads_symbols = test_ads_symbols
        self.ads_preferences = test_ads_preferences


if __name__ == "__main__":

    # test_candidates = [
    #     "Nickel",
    #     "Clay",
    #     "Cobalt oxide",
    #     "Zeolites",
    #     "CuO2",
    #     "Platinum-doped nickel",
    #     "Nickel-based catalysts",
    #     "NiMnCu",
    # ]
    test_candidates = [
        ["Ni"],
        # None,
        # "Cobalt oxide",
        # None,
        # "CuO2",
        ["Pt", "Ni"],
        ["Ni"],
        ["Ni", "Mn", "Cu"],
    ]
    test_ads_symbols = ["CO", "H2O", "CO2"]
    test_ads_preferences = [-1, 1, 1]

    test_state = {
        "candidates": test_candidates,
        "ads_symbols": test_ads_symbols,
        "ads_preferences": test_ads_preferences,
    }
    test_state = _TestState(test_candidates, test_ads_symbols, test_ads_preferences)
    sr = StructureReward(
        **{
            "model": "gemnet",
            "traj_dir": Path("data/output_data/trajectories/pipeline_test"),
        }
    )
    import time

    start = time.time()
    reward = sr(test_state)
    end = time.time()
    print(end - start)
    print(reward)
