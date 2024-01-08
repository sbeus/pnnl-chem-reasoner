"""Module for reward funciton by calculation of adsorption energies in simulation."""
import logging
import sys
import uuid
from pathlib import Path
import numpy as np

from ase import Atoms
from ase.io import read
from ase.data import chemical_symbols


sys.path.append("src")
from llm import ase_interface  # noqa: E402
from search.state.reasoner_state import ReasonerState  # noqa: E402
from evaluation.break_traj_files import break_trajectory  # noqa: E402
from nnp import oc  # noqa: E402
from search.reward.base_reward import BaseReward  # noqa: E402
import pandas as pd
import pickle
from typing import List
import argparse
from omegaconf import OmegaConf

logging.getLogger().setLevel(logging.INFO)


class PathReward(BaseReward):
    """Calculate the reward for answers based on adsorption simulations."""

    def __init__(
        self,
        llm_function: callable,
        penalty_value: float = -10,
        nnp_class="oc",
        num_slab_samples=16,
        num_adslab_samples=16,
        **nnp_kwargs,
    ):
        """Select the class of nnp for the reward function."""
        self.llm_function = llm_function
        self.penalty_value = penalty_value
        if nnp_class == "oc":
            self.adsorption_calculator = oc.OCAdsorptionCalculator(**nnp_kwargs)
        else:
            raise NotImplementedError(f"No such nnp class {nnp_class}.")
        self.num_slab_samples = num_slab_samples
        self.num_adslab_samples = num_adslab_samples


    def __call__(
        self,
        paths
    ):
        """Return the calculated adsorption energy from the predicted catalysts."""

        _, min_act_energy, min_act_energy_path = self.get_reward_for_paths(paths)

        print("minimum activation energy aproximation: ", min_act_energy)
        print("minimum activation energy reaction pathway: ", min_act_energy_path)

        return min_act_energy_path

    def create_structures_and_calculate(
        self,
        slab_syms,
        ads_list,
        candidates_list=None,
        adsorbate_height=1,
        placement_type=None,
    ):
        """Create the structures from the symbols and calculate adsorption energies."""
        start_gnn_calls = self.adsorption_calculator.gnn_calls
        start_gnn_time = self.adsorption_calculator.gnn_time
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
                    print('slab is not present. creating new one.')
                    try:
                        slab_samples = [
                            ase_interface.symbols_list_to_bulk(slab_sym)
                            for _ in range(self.num_slab_samples)
                        ]
                        print(slab_samples)
                    except ase_interface.StructureGenerationError as err:
                        print(err)
                        slab_syms[i] = None
                        valid_slab_sym = False

                    if valid_slab_sym:
                        slab_ats = self.adsorption_calculator.choose_slab(
                            slab_samples, slab_name
                        )
                if slab_ats is not None:
                    print('salb is present')
                    if placement_type == None:
                        for ads_sym in ads_list:
                            ads_ats = ase_interface.ads_symbols_to_structure(ads_sym)
                            name = f"{slab_name}_{ads_sym}"
                            adslab_ats += self.sample_adslabs(
                                slab_ats, ads_ats, name, adsorbate_height
                            )
                            if candidates_list is not None:
                                name_candidate_mapping[name] = candidates_list[i]

                    elif placement_type == "heuristic":
                        for ads_sym in ads_list:
                            ads_ats = ase_interface.ads_symbols_to_structure(ads_sym)
                            # slab_ats.center(vacuum=13.0, axis=2)

                            name = f"{slab_name}_{ads_sym}"
                            adslab_ats += self.sample_adslabs_heuristic(slab_ats, ads_ats, name)

                            if candidates_list is not None:
                                name_candidate_mapping[name] = candidates_list[i]

        adslabs_and_energies = self.create_batches_and_calculate(adslab_ats)

        end_gnn_calls = self.adsorption_calculator.gnn_calls
        end_gnn_time = self.adsorption_calculator.gnn_time

        return (
            adslabs_and_energies,
            end_gnn_calls - start_gnn_calls,
            end_gnn_time - start_gnn_time,
            name_candidate_mapping,
        )

    def parse_adsorption_energies(
        self,
        adslabs_and_energies,
        name_candidate_mapping,
        candidates_list,
        ads_preferences,
    ):
        """Parse adsorption energies to get the reward value."""
        # Parse out the rewards into candidate/adsorbate
        reward_values = {}
        for idx, name, energy, valid_structure in adslabs_and_energies:
            cand = name_candidate_mapping[name]
            ads = name.split("_")[-1]
            if valid_structure:
                if cand in reward_values.keys():
                    reward_values[cand][ads] += [energy]
                else:
                    reward_values[cand] = {ads: [energy]}
            else:
                if cand not in reward_values.keys():
                    reward_values[cand] = {ads: []}

        # aggregate the rewards
        rewards = []
        for cand in candidates_list:
            if cand in reward_values.keys():
                rewards.append(
                    [
                        -((min(reward_values[cand][ads])) ** ads_preferences[i])
                        if reward_values[cand][ads] > 0
                        else self.penalty_value
                        for i, ads in enumerate(reward_values[cand].keys())
                    ]
                )
            else:  # Handle default here TODO: determine some logic/pentaly for this
                print(cand)
                return rewards.append(self.penalty_value)

        final_reward = np.mean(rewards)

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
            if (
                len(
                    list(
                        self.adsorption_calculator.traj_dir.rglob(str(fname) + "*.traj")
                    )
                )
                == 0
            ):
                print("****")
                print(adslab)
                adslab_batch.append(adslab)
                fname_batch.append(str(fname) + f"-{uuid.uuid4()}")
            else:
                idx = str(fname.stem)
                name = str(fname.parent)

                # Get pre calculated values if they exists. Otherwise, create batch
                # ads_calc = self.adsorption_calculator.get_prediction(name, idx)
                ads_calc = self.adsorption_calculator.get_prediction2(name, idx)
                if ads_calc is not None:
                    valid = self.adsorption_calculator.get_validity(name, idx)
                    results.append((idx, name, ads_calc, valid))
                else:
                    adslab_batch.append(adslab)
                    fname_batch.append(str(fname) + f"-{uuid.uuid4()}")

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

    def get_reward_for_path(self, path: list):
    
        adsE=[]
        # reward_values = defaultdict()
        for j, step in enumerate(path):
            adsorbent, adsorbate, name = step    
            print('step: ', j)
    
            # use the same adsorbent
            # create the adsorbent here or if the slab is
            # saved, read it.
            res = sr.create_structures_and_calculate(
                    [ adsorbent ],
                    [ adsorbate ],
                    [ name ],
                    placement_type="heuristic"
                )
    
            for p in Path("data", "output", f"{traj_dir}").rglob("*.traj"):
                    break_trajectory(p)
            
            adslabs_and_energies = res[0] # id, slab_name, ads_energy, valid
            name_candidate_mapping = res[3]
            # adslabs_and_energies
    
            # only selecting the valid structures
            adslabs_and_energies = [i for i in adslabs_and_energies if i[3]==1]
            
            # get the energies of each adsorbed structures
            # energies = [i[2] for i in adslabs_and_energies] # before
            energies = [i[2][0] for i in adslabs_and_energies] # getting adsorption energies
    
            # get the minimum energy structure
            lowest_E_str = adslabs_and_energies[np.argmin(energies)]
        
            print("low E ", lowest_E_str)
            adsE.append(lowest_E_str)
        
        # E = [i[2] for i in adsE] # before
        E_adsorbate_ref = np.array([i[2][1] for i in adsE]) # adsorbate reference energies
        E_adsorption = np.array([i[2][0] for i in adsE]) # Adsorption energies
        E_relax_composite = E_adsorption + E_adsorbate_ref # Relaxed energy" of the adsorbent+adsorbate composite
        
        # E = [i[2][1] for i in adsE] # new, using the relaxed energies to find the activation energy
        lowestE_ids = [i[0] for i in adsE] # return this. is there a better way to get this? #TODO
        lowestE_names = [i[1] for i in adsE] # return this.
        
        # print('energy difference between steps: ', np.diff(E) )
        print('energy difference between steps: ', np.diff(E_relax_composite) )
        # max_E_diff = max(np.diff(E)) # an approximation for activation energy # before
        max_E_diff = max(np.diff(E_relax_composite)) # an approximation for activation energy # new
    
        return max_E_diff, E_relax_composite, lowestE_ids, lowestE_names, E_adsorption, E_adsorbate_ref

    def get_reward_for_paths(self, paths):
        rewards = []
        relax_energies, adsorption_energies, adsorbate_energies = [], [], []
        lowestE_str = []
        for path in paths:
            # have to get path name
            reward, E, lowestE_ids, lowestE_names, E_adsorption, E_adsorbate_ref = self.get_reward_for_path(path)
            # min_act_energy_path_id, relax_energies, min_act_energy, min_act_energy_path, lowestE_str[min_act_energy_path_id]
            relax_energies.append(E) # relaxed energies of all the steps.
            rewards.append(reward) # activation energy
            lowestE_str.append((lowestE_ids, lowestE_names))

            adsorption_energies.append(E_adsorption)
            adsorbate_energies.append(E_adsorbate_ref)
    
        min_act_energy_path_id = np.argmin(rewards)
        min_act_energy = rewards[min_act_energy_path_id]
        min_act_energy_path = paths[min_act_energy_path_id]

        # returning ads_energies for each step, in case they are
        # needed for visualization purposes
        return min_act_energy_path_id, relax_energies, min_act_energy, min_act_energy_path, lowestE_str[min_act_energy_path_id], rewards, adsorption_energies, adsorbate_energies


    def unpack_batch_results(self, batch_results, fname_batch):
        """Unpack a collection of batch results."""
        results = []
        for i, res in enumerate(batch_results):
            idx = Path(fname_batch[i]).stem.split("-")[0]
            name = str(Path(fname_batch[i]).parent)
            valid = self.adsorption_calculator.get_validity(name, idx)
            results.append((idx, name, res, valid))
        return results

    # use this to get both adsorption energy and the adsorbate reference energy
    def calculate_batch(self, adslab_batch, fname_batch):
        """Calculate adsorption energies for a batch of atoms objects."""
        batch_relaxed = self.adsorption_calculator.batched_relax_atoms(
            atoms=adslab_batch, atoms_names=fname_batch
        )
        batch_adsorption_energies = (
            # returns both adsorption energy and the relaxed_energy of the
            # adsorbate+adsorbent system
            self.adsorption_calculator.batched_adsorption_and_energy_calculation(
                atoms=batch_relaxed, atoms_names=fname_batch
            )
        )
        return batch_adsorption_energies

    def sample_adslabs(self, slab, ads, name, adsorbate_height):
        """Sample possible adsorbate+slab combinations."""
        adslabs = []
        for i in range(self.num_adslab_samples):
            print(slab.info)
            adslab = ase_interface.generate_bulk_ads_pairs(
                slab, ads, height=adsorbate_height
            )
            adslabs.append((i, name, adslab))
        return adslabs

    def sample_adslabs_heuristic(self, slab, ads, name):
        """Sample possible adsorbate+slab combinations."""
        adslabs = []
        # for i in range(self.num_adslab_samples):
        # print(slab.info)
        adslab = ase_interface.generate_bulk_ads_pairs_heuristic(slab, ads, num_sites=self.num_adslab_samples)
        adslabs = [(i, name, adslab[i]) for i in range(len(adslab))]

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
    def reduce_candidate_symbols(candidate_syms: List[str]):
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


# class _TestState:
#     def __init__(self, test_candidates, test_ads_symbols, test_ads_preferences):
#         """Create test query state for testing the reward function."""
#         self.candidates = test_candidates
#         self.ads_symbols = test_ads_symbols
#         self.ads_preferences = test_ads_preferences
    



if __name__ == "__main__":
    # traj_dir = "hreact2"

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help="configuration file *.yml", type=str, required=False, default='config.yaml')
    args = parser.parse_args()

    if args.config:  # args priority is higher than yaml
        opt = OmegaConf.load(args.config)
        OmegaConf.resolve(opt)

        args=opt

    traj_dir = args.traj_dir
    path_file = args.path_file

    sr = PathReward(
            **{
                "llm_function": None,
                "model": "gemnet",
                "traj_dir": Path("data", "output", f"{traj_dir}"),
                "device": "cuda",
                "ads_tag": 2,
                # "num_adslab_samples": 16
                "num_adslab_samples": 4
            }
        )

    # with open(path_file, 'rb') as f:
    #     pathways = pickle.load(f)

    pathways = pd.read_pickle(path_file)

    # pathways ==>
    # {'CuZn': {'CuZn_0': [[['Cu', 'Zn'], 'CO2', 'CuZn'],
    #    [['Cu', 'Zn'], '*OCHO', 'CuZn'],
    #    [['Cu', 'Zn'], '*CHOH', 'CuZn'],
    #    [['Cu', 'Zn'], '*OHCH3', 'CuZn']],
    #   'CuZn_1': [[['Cu', 'Zn'], 'CO2', 'CuZn'],
    #    [['Cu', 'Zn'], '*CO', 'CuZn'],
    #    [['Cu', 'Zn'], '*CHO', 'CuZn'],
    #    [['Cu', 'Zn'], '*CH2*O', 'CuZn'],
    #    [['Cu', 'Zn'], '*OHCH3', 'CuZn']]},
    #  'CuAu': {'CuAu_0': [[['Cu', 'Au'], 'CO2', 'CuAu'],
    #    [['Cu', 'Au'], '*OCHO', 'CuAu'],
    #    [['Cu', 'Au'], '*CHOH', 'CuAu'],
    #    [['Cu', 'Au'], '*OHCH3', 'CuAu']],
    #   'CuAu_1': [[['Cu', 'Au'], 'CO2', 'CuAu'],
    #    [['Cu', 'Au'], '*CO', 'CuAu'],
    #    [['Cu', 'Au'], '*CHO', 'CuAu'],
    #    [['Cu', 'Au'], '*CH2*O', 'CuAu'],
    #    [['Cu', 'Au'], '*OHCH3', 'CuAu']]},

    for slab_name, slab_pathways in pathways.items():
        # slab_name ==> 'CuZn'

     

        path_list = list(slab_pathways.values())

        min_act_energy_path_id, relax_energies, min_act_energy, min_act_energy_path, lowestE_str_info, rewards, adsorption_energies, adsorbate_energies = sr.get_reward_for_paths(path_list)
    

        print("min_act_energy_path_id: ", min_act_energy_path_id)
        print('relaxed energies: ', relax_energies)
        print("minimum act. energy: ", min_act_energy)
        print("minimum act. energy path : ", min_act_energy_path)
        print("minimum act. energy path info : ", lowestE_str_info)

        output = {
        
        "trag_dir": traj_dir,
        "rewards": rewards,
        "adsorption_energies": adsorption_energies,
        "adsorbate_energies": adsorbate_energies,
        "min_act_energy_path_id": min_act_energy_path_id,
        "relaxed_energies": relax_energies,
        "minimum_act_energy": min_act_energy,
        "minimum_act_energy_path": min_act_energy_path,
        "minimum_act_energy_path_info_": lowestE_str_info,
        "slab_names": list(slab_pathways.keys())
        }

        result_file_name = f"paths_results_{slab_name}.pkl"
        out_path = Path("data", "output", f"{traj_dir}", result_file_name)

        with open(out_path, 'wb') as f:
            pickle.dump(output, f)


