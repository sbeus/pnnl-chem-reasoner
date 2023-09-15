"""Module for reward funciton by calculation of adsorption energies in simulation."""
import json
import math
import sys

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

    def __init__(
        self, nnp_class="oc", num_slab_samples=8, num_adslab_samples=8, **nnp_kwargs
    ):
        """Select the class of nnp for the reward function."""
        if nnp_class == "oc":
            self.adsorption_calculator = oc.OCAdsorptionCalculator(**nnp_kwargs)
        else:
            raise NotImplementedError(f"No such nnp class {nnp_class}.")
        self.num_slab_samples = num_slab_samples
        self.num_adslab_samples = num_adslab_samples

    def __call__(self, s: query.QueryState):
        """Return the calculated adsorption energy from the predicted catalysts."""
        candidates_list = s.candidates
        ads_list = s.ads_symbols
        slab_syms = ase_interface.llm_answer_to_symbols(candidates_list, debug=s.debug)

        adslab_ats = []  # List to store initial adslabs and indices
        name_candidate_mapping = (
            {}
        )  # dictionary to get from database names to candidates
        for i, slab_sym in enumerate(slab_syms):
            if slab_sym is not None:
                valid_slab_sym = True
                slab_name = self.reduce_candidate_symbols(slab_sym)
                slab_ats = self.adsorption_calculator.get_slab(slab_name)
                if slab_ats is None:
                    try:
                        slab_samples = [
                            ase_interface.symbols_list_to_bulk(slab_sym)
                            for _ in range(self.num_slab_samples)
                        ]
                    except ase_interface.StructureGenerationError as err:
                        slab_syms[i] = None
                        print(f"\n*\n*\n*\n{str(err)}\n*\n*\n*\n*")
                        valid_slab_sym = False

                    if valid_slab_sym:
                        slab_ats = self.adsorption_calculator.choose_slab(
                            slab_samples, slab_name
                        )
                if slab_ats is not None:
                    for ads_sym in ads_list:

                        ads_ats = ase_interface.ads_symbols_to_structure(ads_sym)
                        name = f"{slab_name}_{ads_sym}"
                        adslab_ats += self.sample_adslabs(slab_ats, ads_ats, name)
                        name_candidate_mapping[name] = candidates_list[i]
        adslabs_and_energies = self.create_batches_and_calculate(
            adslab_ats,
        )
        # Parse out the rewards into candidate/adsorbate
        reward_values = {}
        for idx, name, energy in adslabs_and_energies:
            cand = name_candidate_mapping[name]
            ads = name.split("_")[-1]
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
                print(cand)
        final_reward = np.mean(rewards)
        s.reward = final_reward
        return final_reward  # return mean over candidates

    def create_batches_and_calculate(self, adslabs):
        """Split adslabs into batches and run the simulations."""
        print("\n\n\nCreate batches and calcualte\n\n\n")
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
                print("****")
                print(adslab)
                adslab_batch.append(adslab)
                fname_batch.append(str(fname))
            else:
                idx = str(fname.stem)
                name = str(fname.parent)

                # Get pre calculated values if they exists. Otherwise, create batch
                ads_calc = self.adsorption_calculator.get_prediction(name, idx)
                if ads_calc is not None:
                    results.append((idx, name, ads_calc))
                else:
                    adslab_batch.append(adslab)
                    fname_batch.append(str(fname))

            # dispatch the batch
            if len(adslab_batch) == self.adsorption_calculator.batch_size:
                batch_results = self.calculate_batch(adslab_batch, fname_batch)
                results += self.unpack_batch_results(batch_results, fname_batch)
                adslab_batch = []
                fname_batch = []
        # dispatch the remaining batch
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

    def sample_adslabs(self, slab, ads, name):
        """Sample possible adsorbate+slab combinations."""
        adslabs = []
        for i in range(self.num_adslab_samples):
            print(slab.info)
            adslab = ase_interface.generate_bulk_ads_pairs(slab, ads)
            adslabs.append((i, name, adslab))
        return adslabs

    @staticmethod
    def reduce_metal_symbols(metal_ats: Atoms):
        """Reduce the symbols of metal symbols to a basic form.

        If there are two metals, the more prominant metal is listed first. If there are
        three, the metals are listed in alphabetical order.
        """
        numbers = metal_ats.get_atomic_numbers()
        syms_count = {}
        for num in numbers:
            sym = chemical_symbols[num]
            if sym in syms_count.keys():
                syms_count[sym] += 1
            else:
                syms_count[sym] = 1

        if len(syms_count) == 2:
            k1, k2 = syms_count.keys()
            if syms_count[k1] > syms_count[k2]:
                name_syms = [k1, k2]
            else:
                name_syms = [k2, k1]
        else:

            name_syms = sorted(list(syms_count.keys()))

        formula = "".join(name_syms)
        return formula

    @staticmethod
    def reduce_candidate_symbols(candidate_syms: list[str]):
        """Reduce the symbols of metal symbols to a basic form.

        If there are two metals, the more prominant metal is listed first. If there are
        three, the metals are listed in alphabetical order.
        """
        print(candidate_syms)
        if len(candidate_syms) == 1:
            formula = candidate_syms[0]
        if len(candidate_syms) == 2:
            formula = "".join(candidate_syms)
        else:
            formula = candidate_syms[0] + "".join(sorted(list(candidate_syms)[1:]))

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
