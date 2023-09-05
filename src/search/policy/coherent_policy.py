"""Class for the coherence policy."""
import sys

from abc import Callable, Optional
from pathlib import Path

import numpy as np

sys.path.append(Path("src"))

from search.policy.reasoner_policy import ReasonerPolicy  # noqa:402


class CoherentPolicy(ReasonerPolicy):
    """A polocy like the Reasoner policy, but it promotes more coherent prompts."""

    def __init__(
        self,
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

        def get_actions(
            self, state: object
        ) -> tuple[list[Callable[object, object]], np.array]:
            """Return the actions along with their priors."""
            actions, priors = super().get_actions(state)

            # generate the trial states
            trial_states = []
            for a in actions:
                trial_states.append(a(state, trial=True))
