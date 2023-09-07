"""Search tree implemenation."""
from pathlib import Path
import pickle
import time

from random import shuffle

from typing import TypeVar

import numpy as np

SearchTree = TypeVar("SearchTree")


class BeamSearchTree:
    """A class for running monte carlo tree search."""

    def __init__(self, data, policy, reward_fn, num_generate, num_keep):
        """Create a SearchTree from root node."""
        self.num_generate = num_generate
        self.num_keep = num_keep
        self.policy = policy
        self.reward_fn = reward_fn
        self.nodes = []
        self.nodes.append([data])
        self.parent_idx = [[-1]]
        self.node_rewards = [[0]]
        self.generated_nodes = [[]]
        self.generated_node_rewards = [[]]
        self.generated_parent_idx = [[]]

        self.start_time = None
        self.end_time = None
        # expand the root node

    def expand_node(self, node):
        """Expand out possible sub-nodes for given node."""
        actions, priors = self.policy.get_actions(node)
        shuffle_idx = list(range(len(priors)))
        shuffle(shuffle_idx)
        priors = [priors[i] for i in shuffle_idx]
        actions = [actions[i] for i in shuffle_idx]

        action_idxs = np.argsort(priors)[-self.num_generate :]  # noqa: E203

        new_nodes = []
        for i in action_idxs:
            if priors[i] > 0:
                a = actions[i]
                new_nodes.append(a(node))
        return new_nodes

    def simulation_policy(self):
        """Simulate a beam search step."""
        if self.start_time is None:
            self.start_timer()
        nodes = self.nodes[-1]

        successor_nodes = []
        successor_rewards = []
        parent_idx = []
        for i, n in enumerate(nodes):
            next_nodes = self.expand_node(n)
            rewards = [self.reward_fn(n) for n in next_nodes]
            successor_nodes += next_nodes
            successor_rewards += rewards
            parent_idx += [i] * len(next_nodes)
        selected_node_idx = np.argsort(successor_rewards)[
            -self.num_keep :  # noqa: E203
        ]
        generated_idx = np.argsort(successor_rewards)[: -self.num_keep]  # noqa: E203

        selected_nodes = [successor_nodes[i] for i in selected_node_idx]
        selected_rewards = [successor_rewards[i] for i in selected_node_idx]
        selected_parents = [parent_idx[i] for i in selected_node_idx]

        generated_nodes = [successor_nodes[i] for i in generated_idx]
        generated_node_rewards = [successor_rewards[i] for i in generated_idx]
        generated_parent_idx = [parent_idx[i] for i in generated_idx]

        self.nodes.append(selected_nodes)
        self.node_rewards.append(selected_rewards)
        self.parent_idx.append(selected_parents)

        self.generated_nodes.append(generated_nodes)
        self.generated_node_rewards.append(generated_node_rewards)
        self.generated_parent_idx.append(generated_parent_idx)

    def start_timer(self):
        """Save the time to the start time."""
        self.start_time = time.time()

    def end_timer(self):
        """Save a number to the end timer."""
        self.end_time = time.time()

    def get_time(self):
        """Save a number to the end timer."""
        return self.end_time - self.start_time

    def reset_timer(self):
        """Reset the time values to None."""
        self.start_time = None
        self.end_time = None

    def get_processed_data(self) -> dict:
        """Turn beam search tree into dictionary for saving."""
        beam_search_daata = dict()
        beam_search_daata["nodes"] = []
        for list_nodes in self.nodes:
            beam_search_daata["nodes"].append([vars(n) for n in list_nodes])
        beam_search_daata["node_rewards"] = self.node_rewards
        beam_search_daata["parent_idx"] = self.parent_idx

        beam_search_daata["generated_nodes"] = []
        for list_nodes in self.generated_nodes:
            beam_search_daata["generated_nodes"].append([vars(n) for n in list_nodes])
        beam_search_daata["generated_node_rewards"] = self.generated_node_rewards
        beam_search_daata["generated_parent_idx"] = self.generated_parent_idx

        beam_search_daata["num_generate"] = self.num_generate
        beam_search_daata["num_keep"] = self.num_keep

        beam_search_daata["start_time"] = self.start_time
        beam_search_daata["end_time"] = self.end_time

        return beam_search_daata

    def pickle(self, fname: Path):
        """Save beam search to pickle file."""
        pickle_data = self.get_processed_data()
        with open(fname, "wb") as f:
            pickle.dump(pickle_data, f)

    def step_save(self, fname):
        """Take a simulation step and save the resulting tree state with end_time."""
        self.simulation_policy()
        self.end_timer()
        self.pickle(fname)
