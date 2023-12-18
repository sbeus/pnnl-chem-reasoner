"""Class for the coherence policy."""
import sys

from collections.abc import Callable

import numpy as np
from scipy.special import softmax
from sklearn.preprocessing import MinMaxScaler
from sklearn.exceptions import NotFittedError

sys.path.append("src")
from search.policy.reasoner_policy import ReasonerPolicy  # noqa:402
from search.state.reasoner_state import ReasonerState  # noqa:402


class CoherentPolicy(ReasonerPolicy):
    """A polocy like the Reasoner policy, but it promotes more coherent prompts."""

    def __init__(
        self,
        temperature: float = 0.6,
        include_property_types: list[str] = None,
        exclude_property_types: list[str] = None,
        relationship_to_candidate_list_types: list[str] = None,
        catalyst_label_types: list[str] = None,
        try_oxides: bool = True,
    ):
        """Create the underlying ReasonerPolicy."""
        super().__init__(
            include_property_types,
            exclude_property_types,
            relationship_to_candidate_list_types,
            catalyst_label_types,
            try_oxides,
        )
        self.temperature = temperature
        self.min_max = MinMaxScaler()
        self.min_max.fit([[0]])  # initialize one value

    def set_min_max_data(self, x: float):
        """Set the min max function from data."""
        x = [[x]]
        self.min_max.fit(x)

    def update_min_max_data(self, x: float):
        """Set the min max function from data."""
        x = [[x]]
        self.min_max.partial_fit(x)

    def transform_reward(self, x: float):
        """Set the min max function from data."""
        x = [[x]]
        try:
            return self.min_max.transform(x)[0][0]
        except NotFittedError:
            self.update_min_max_data(x)
            return self.min_max.transform(x)[0][0]

    @classmethod
    @staticmethod
    def from_reasoner_policy(
        reasoner_policy: ReasonerPolicy, temperature: float = 0.6
    ) -> "CoherentPolicy":
        """Construct a coherent policy from a reasoner poliy."""
        p = CoherentPolicy()
        p.actions = reasoner_policy.actions.copy()
        p.init_weights()
        return p

    def get_actions(
        self, state: object
    ) -> tuple[list[Callable[object, object]], np.array]:
        """Return the actions along with their priors."""
        actions, priors = super().get_actions(state)
        # generate the trial states
        trial_states = []
        idx_trial_states = []  # mask for iompossible trial states
        for i, a in enumerate(actions):
            if priors[i] > 0:
                trial_states.append(a(state, trial=True))
                idx_trial_states.append(i)

        sim_scores = state.similarity(trial_states)

        full_sim_scores = np.zeros_like(priors)
        full_sim_scores[np.array(idx_trial_states)] = np.array(sim_scores)
        if state.reward is not None:
            reward_adjustment = full_sim_scores * (
                self.transform_reward(state.reward)
            ) + (1 - full_sim_scores) * (1 - self.transform_reward(state.reward))
        else:
            reward_adjustment = full_sim_scores

        state.info["priors"].update({"reward_adjusted_similarities": reward_adjustment})
        state.info["priors"].update(
            {"reward_adjustment_value": self.transform_reward(state.reward)}
        )

        new_priors = (
            softmax((reward_adjustment / self.temperature).astype(float)) * priors
        )
        new_priors = new_priors / np.sum(new_priors)  # re-normalize
        state.info["priors"].update({"values": new_priors})

        return actions, new_priors


def coherent_measure(
    states: list[ReasonerState], llm_function: callable = None
) -> float:
    """Measure the coherence of a given sequence of states."""
    prompts = []
    system_prompts = []
    answers = []
    for s in states:
        prompts.append(s.generation_prompt)
        system_prompts.append(s.generation_system_prompt)
        answers.append(s.answer)
    return -np.inf


if __name__ == "__main__":
    import pickle

    with open("data/example_trajectory.pkl", "rb") as f:
        states = pickle.load(f)

    coherent_measure(states)
