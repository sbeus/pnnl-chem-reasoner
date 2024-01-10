"""Run the queries for ICML."""
import argparse
import json
import logging
import os
import sys
import time

from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("src")
from datasets import reasoner_data_loader  # noqa:E402
from llm.azure_open_ai_interface import run_azure_openai_prompts  # noqa:E402
from search.policy import coherent_policy, reasoner_policy  # noqa:E402
from search.reward import simulation_reward, reaction_reward, llm_reward  # noqa:E402
from search.methods.tree_search.beam_search import BeamSearchTree  # noqa:E402
from search.state.reasoner_state import ReasonerState  # noqa:E402

logging.getLogger().setLevel(logging.INFO)

# TODO: Complete arguments for each of these getter functions


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)


def get_search_method(args, data, policy, reward_fn):
    """Get the search method provided in args."""
    if args.search_method == "beam-search":
        assert isinstance(args.num_keep, int) and args.num_keep > 0, "invalid parameter"
        assert (
            isinstance(args.num_generate, int) and args.num_generate > 0
        ), "invalid parameter"
        return BeamSearchTree(
            data,
            policy,
            reward_fn,
            num_generate=args.num_generate,
            num_keep=args.num_keep,
        )
    elif args.search_method == "mcts":
        raise NotImplementedError("Monte Carlo Tree Search is not implemented, yet.")
    else:
        raise NotImplementedError(f"Unkown Search strategy {args.search_method}.")


def get_reward_function(args, state, llm_function):
    """Get the reward function provided in args."""
    assert (
        isinstance(args.penalty_value, float) and args.penalty_value < 0
    ), "invalid parameter"
    assert (
        isinstance(args.reward_max_attempts, int) and args.reward_max_attempts > 0
    ), "invalid parameter"

    if args.reward_function == "simulation-reward":
        if state.reaction_pathways is None:
            assert (
                isinstance(args.nnp_class, str) and args.nnp_class == "oc"
            ), "invalid parameter"
            assert (
                isinstance(args.num_slab_samples, int) and args.num_slab_samples > 0
            ), "invalid parameter"
            assert (
                isinstance(args.num_adslab_samples, int) and args.num_adslab_samples > 0
            ), "invalid parameter"

            # check nnp_kwargs
            assert (
                isinstance(args.reward_max_attempts, int)
                and args.reward_max_attempts > 0
            ), "invalid parameter"
            assert args.gnn_model == "gemnet", "invalid parameter"
            assert isinstance(args.gnn_traj_dir, str), "invalid parameter"
            assert (
                isinstance(args.gnn_batch_size, int) and args.gnn_batch_size > 0
            ), "invalid parameter"
            assert isinstance(args.gnn_device, str) and (
                args.gnn_device == "cpu" or args.gnn_device == "cuda"
            ), "invalid parameter"
            assert (
                isinstance(args.gnn_ads_tag, int) and args.gnn_ads_tag == 2
            ), "invalid parameter"
            assert (
                isinstance(args.gnn_fmax, float) and args.gnn_fmax > 0
            ), "invalid parameter"
            assert (
                isinstance(args.gnn_steps, int) and args.gnn_steps >= 0
            ), "invalid parameter"
            nnp_kwargs = {
                "model": args.gnn_model,
                "traj_dir": Path(args.gnn_traj_dir),
                "batch_size": args.gnn_batch_size,
                "device": args.gnn_device,
                "ads_tag": args.gnn_ads_tag,
                "fmax": args.gnn_fmax,
                "steps": args.gnn_steps,
            }
            return simulation_reward.StructureReward(
                llm_function=llm_function,
                penalty_value=args.penalty_value,
                nnp_class=args.nnp_class,
                num_slab_samples=args.num_slab_samples,
                num_adslab_samples=args.num_adslab_samples,
                max_attempts=args.reward_max_attempts,
                **nnp_kwargs,
            )
        else:
            return reaction_reward.PathReward

    elif args.reward_function == "llm-reward":
        assert isinstance(args.reward_limit, float), "invalid parameter"
        return llm_reward.LLMRewardFunction(
            llm_function,
            reward_limit=args.reward_limit,
            max_attempts=args.reward_max_attempts,
            penalty_value=args.penalty_value,
        )
    else:
        raise NotImplementedError(f"Unknown reward function {args.reward_function}.")


def get_policy(args, llm_function: callable = None):
    """Get the policy provided in args."""
    if args.policy == "coherent-policy":
        assert isinstance(args.max_num_actions, int) and args.max_num_actions > 0
        assert (
            isinstance(args.policy_max_attempts, int) and args.policy_max_attempts > 0
        )
        assert llm_function is not None
        return coherent_policy.CoherentPolicy(llm_function, args.max_num_actions)
    elif args.policy == "reasoner-policy":
        return reasoner_policy.ReasonerPolicy(try_oxides=False)


def get_state_from_idx(idx, df: pd.DataFrame):
    """Get the state referenced by idx."""
    dataset = df.iloc[idx]["dataset"]
    query = df.iloc[idx]["query"]
    return reasoner_data_loader.get_state(dataset, query, chain_of_thought=True)


def get_indeces(args):
    """Get the state indeces provided in args."""
    print(args.start_query)
    assert isinstance(args.start_query, int) and args.start_query >= 0
    assert isinstance(args.end_query, int) and args.end_query > args.start_query
    return list(range(args.start_query, args.end_query))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--savedir", type=str, default=None)
    parser.add_argument("--dataset-path", type=str, default=None)
    parser.add_argument("--start-query", type=int)
    parser.add_argument("--end-query", type=int)
    parser.add_argument("--depth", type=int, default=None)

    # Policy
    parser.add_argument("--policy", type=str, default=None)

    # Coherent Policy
    parser.add_argument("--policy-max-attempts", type=int, default=None)
    parser.add_argument("--max-num-actions", type=int, default=None)

    # Reward function
    parser.add_argument("--reward-function", type=str, default=None)
    parser.add_argument("--penalty-value", type=float, default=None)
    parser.add_argument("--reward-max-attempts", type=int, default=None)

    # Simulation reward

    parser.add_argument("--nnp-class", type=str, default=None)
    parser.add_argument("--num-slab-samples", type=int, default=None)
    parser.add_argument("--num-adslab-samples", type=int, default=None)

    # nnp_kwargs
    parser.add_argument("--gnn-model", type=str, default=None)
    parser.add_argument("--gnn-traj-dir", type=str, default=None)
    parser.add_argument("--gnn-batch-size", type=int, default=None)
    parser.add_argument("--gnn-device", type=str, default=None)
    parser.add_argument("--gnn-ads-tag", type=int, default=None)
    parser.add_argument("--gnn-fmax", type=float, default=None)
    parser.add_argument("--gnn-steps", type=int, default=None)

    parser.add_argument("--search-method", type=str, default=None)
    parser.add_argument("--num-keep", type=int, default=None)
    parser.add_argument("--num-generate", type=int, default=None)

    # llm reward
    parser.add_argument("--reward-limit", type=float, default=None)

    args = parser.parse_args()

    assert isinstance(args.depth, int) and args.depth > 0

    save_dir = Path(args.savedir)
    save_dir.mkdir(parents=True, exist_ok=True)

    llm_function = run_azure_openai_prompts

    df = pd.read_csv(args.dataset_path)
    indeces = get_indeces(args)

    for i in indeces:
        fname = save_dir / f"test_tree_{i}.json"
        starting_state = get_state_from_idx(i, df)

        policy = get_policy(args, llm_function)
        reward_fn = get_reward_function(args, starting_state, llm_function)
        if Path(fname).exists() and os.stat(fname).st_size != 0:
            print(f"Loading a tree from {fname}")
            logging.info("=" * 20 + " " + str(i) + " " + "=" * 20)
            with open(fname, "r") as f:
                tree_data = json.load(f)
                search = BeamSearchTree.from_data(
                    tree_data,
                    policy,
                    reward_fn,
                    node_constructor=ReasonerState.from_dict,
                )
                assert (
                    isinstance(args.num_keep, int) and args.num_keep == search.num_keep
                ), "mismatch parameter"
                assert (
                    isinstance(args.num_generate, int)
                    and args.num_generate == search.num_generate
                ), "mismatch parameter"
        else:
            search = get_search_method(args, starting_state, policy, reward_fn)

        start_time = time.time()
        timing_data = [start_time]
        continue_searching = True
        while len(search) < args.depth and continue_searching:
            try:
                data = search.step_return()
                end_time = time.time()
                timing_data.append(end_time - timing_data[-1])
                with open(fname, "w") as f:
                    data.update(
                        {"total_time": end_time - start_time, "step_times": timing_data}
                    )
                    json.dump(data, f, cls=NpEncoder)
            except Exception as err:
                logging.warning(f"Could not complete search with error: {err}")
                print(f"Could not complete search with error: {err}")
                continue_searching = False

            print("=" * 20 + " " + str(i) + " " + "=" * 20)
            logging.info("=" * 20 + " " + str(i) + " " + "=" * 20)
