"""Functions and classes for querying OpenAI."""
import datetime
import logging
import os

from typing import Union

import backoff

import numpy as np

import openai
from openai.embeddings_utils import get_embedding, cosine_similarity


logging.getLogger().setLevel(logging.INFO)


class QueryState:
    """A class for the search tree state."""

    def __init__(
        self,
        template: str,
        reward_template: str,
        ads_symbols: list[str],
        ads_preferences: list[float] = None,
        catalyst_label: str = " catalysts",
        num_answers: int = 3,
        prev_candidate_list: list[str] = [],
        relation_to_candidate_list: str = None,
        include_list: list[str] = [],
        exclude_list: list[str] = [],
        answer: str = None,
        num_queries=0,
        prediction_model="gpt-3.5-turbo",
        reward_model="gpt-3.5-turbo",
        **kwargs,
    ):
        """Initialize the object."""
        self.template = template
        self.reward_template = reward_template
        self.ads_symbols = ads_symbols.copy()
        if ads_preferences is None:
            self.ads_preferences = [1] * len(self.ads_symbols)
        else:
            self.ads_preferences = ads_preferences.copy()
        self.catalyst_label = catalyst_label
        self.num_answers = num_answers
        self.prev_candidate_list = prev_candidate_list.copy()
        self.relation_to_candidate_list = relation_to_candidate_list
        self.include_list = include_list.copy()
        self.exclude_list = exclude_list.copy()
        self.answer = answer
        self.num_queries = num_queries
        self.prediction_model = prediction_model
        self.reward_model = reward_model

    def copy(self):
        """Return a copy of self."""
        return QueryState(
            template=self.template,
            reward_template=self.reward_template,
            ads_symbols=self.ads_symbols.copy(),
            ads_preferences=self.ads_preferences.copy(),
            catalyst_label=self.catalyst_label,
            prev_candidate_list=self.prev_candidate_list.copy(),
            relation_to_candidate_list=self.relation_to_candidate_list,
            include_list=self.include_list.copy(),
            exclude_list=self.exclude_list.copy(),
            answer=self.answer,
            num_queries=self.num_queries,
            prediction_model=self.prediction_model,
            reward_model=self.reward_model,
        )

    def return_next(self):
        """Return a copy of self."""
        return QueryState(
            template=self.template,
            reward_template=self.reward_template,
            ads_symbols=self.ads_symbols.copy(),
            prev_candidate_list=self.candidates,
            relation_to_candidate_list=self.relation_to_candidate_list,
            include_list=self.include_list.copy(),
            exclude_list=self.exclude_list.copy(),
            answer=None,
            num_queries=0,
            prediction_model=self.prediction_model,
            reward_model=self.reward_model,
        )

    @property
    def prompt(self):
        """Return the prompt for this state."""
        return generate_expert_prompt(
            template=self.template,
            catalyst_label=self.catalyst_label,
            num_answers=self.num_answers,
            candidate_list=self.prev_candidate_list,
            relation_to_candidate_list=self.relation_to_candidate_list,
            include_list=self.include_list,
            exclude_list=self.exclude_list,
        )

    def query(self):
        """Run a query to the LLM and change the state of self."""
        self.answer = self.send_query(self.prompt, model=self.prediction_model)

    @property
    def candidates(self):
        """Return the candidate list of the current answer."""
        return (
            [] if self.answer is None else parse_answer(self.answer, self.num_answers)
        )

    def query_adsorption_energy_list(self, catalyst_slice=slice(None, None)):
        """Run a query to the LLM and change the state of self."""
        retries = 0
        error = None
        while retries < 3:
            retries += 1
            try:
                answers = []
                for ads in self.ads_symbols:
                    candidate_list = self.candidates

                    prompt = generate_adsorption_energy_list_prompt(
                        ads,
                        candidate_list,
                    )
                    answer = self.send_query(
                        prompt,
                        model=self.reward_model,
                        system_prompt=_reward_system_prompt,
                    )

                    number_answers = [
                        abs(float(ans.replace("eV", "")))
                        for ans in parse_answer(answer)
                    ]
                    answers.append(number_answers)

                output = np.mean(
                    [
                        np.mean(ans) ** (self.ads_preferences[i])
                        for i, ans in enumerate(answers)
                    ]
                )
                return output
            except Exception as err:
                error = err
                logging.warning(f"Failed to parse answer with error: {err}.")
                self.query()
        raise error

    def send_query(self, prompt, model=None, system_prompt=None):
        """Send the query to OpenAI and increment."""
        if model is None:
            model = self.prediction_model
        answer = run_query(prompt, model=model, system_prompt=system_prompt)
        self.num_queries += 1
        return answer

    def similarity(
        self, states: "list[QueryState]", model="text-embedding-ada-002"
    ) -> float:
        """Calculate a similarity score of this state with a list of trial states."""
        relevant_strings = [self.prompt, self.answer]
        for state in states:
            relevant_strings.append(state.prompt)
            relevant_strings.append(state.answer)
        embeddings = get_embedding(states, model=model)

        p = embeddings.pop(0)
        y = embeddings.pop(0)
        p_y = p + y
        similarities = []
        while len(embeddings) > 0:
            similarities.append(cosine_similarity(embeddings.pop(0), p_y))

        similarities = np.array(similarities)
        return similarities * self.reward + (1 - similarities) * (1 - self.reward)


_reward_system_prompt = "You are a helpful catalysis expert with extensive knowledge \
    of the adsorption of atoms and molecules. You can offer an approximate value of \
    adsorption energies of various adsorbates to various catalysts."


def generate_adsorption_energy_list_prompt(
    adsorbate: str, candidate_list: list[str], reward_template: str = None
):
    """Make a query to get a list of adsorption energies."""
    if reward_template is None:
        prompt = (
            "Generate a list of adsorption energies, in eV, "
            f"for the adsorbate {adsorbate} to the surface of "
            f"each of the following catalysts: {', '.join(candidate_list)}. "
            f"Return the adsorption energies as a list of only {len(candidate_list)} "
            "numbers in the order specified."
        )
    else:
        vals = {"adsorbate": adsorbate, "candidate_list": candidate_list}
        prompt = fstr(reward_template, vals)
    return prompt


def generate_expert_prompt(
    template: str,
    catalyst_label: str,
    num_answers: int,
    candidate_list: list = [],
    relation_to_candidate_list: str = None,
    include_list: list = [],
    exclude_list: list = [],
):
    """Generate prompt based on catalysis experts."""
    if len(candidate_list) != 0 and relation_to_candidate_list is not None:
        candidate_list_statement = f"{relation_to_candidate_list} "
        candidate_list_statement += ", ".join(candidate_list).strip() + " "
    elif len(candidate_list) != 0 and relation_to_candidate_list is None:
        raise ValueError(
            f"Non-empty candidate list {candidate_list} given with "
            "relation_to_candidate_list == None"
        )
    else:
        candidate_list_statement = ""
    if len(include_list) != 0:
        include_statement = (
            f"Include candidate{catalyst_label} with the following properties: "
        )
        include_statement += ", ".join(include_list)
        include_statement += ". "
    else:
        include_statement = ""
    if len(exclude_list) != 0:
        exclude_statement = (
            f"Exclude candidate{catalyst_label} with the following properties: "
        )

        exclude_statement += ", ".join(exclude_list)
        exclude_statement += ". "
    else:
        exclude_statement = ""
    vals = {
        "catalyst_label": catalyst_label,
        "candidate_list_statement": candidate_list_statement,
        "include_statement": include_statement,
        "exclude_statement": exclude_statement,
    }
    return fstr(template, vals)


def fstr(fstring_text, vals):
    """Evaluate the provided fstring_text."""
    ret_val = eval(f'f"{fstring_text}"', vals)
    return ret_val


def generate_oc_prompt(
    adsorbate: str,
    catalyst_label: str,
    num_answers: int,
    candidate_list: list = [],
    relation_to_candidate_list: str = None,
    include_list: list = [],
    exclude_list: list = [],
):
    """Generate prompt to query for adsorption energy."""
    if len(candidate_list) != 0 and relation_to_candidate_list is not None:
        candidate_list_statement = f"{relation_to_candidate_list} "
        candidate_list_statement += ", ".join(candidate_list).strip() + " "
    elif len(candidate_list) != 0 and relation_to_candidate_list is None:
        raise ValueError(
            f"Non-empty candidate list {candidate_list} given with "
            "relation_to_candidate_list == None"
        )
    else:
        candidate_list_statement = ""
    if len(include_list) != 0:
        include_statement = (
            f"Include candidate{catalyst_label} with the following properties: "
        )
        include_statement += ", ".join(include_list)
        include_statement += ". "
    else:
        include_statement = ""
    if len(exclude_list) != 0:
        exclude_statement = (
            f"Exclude candidate{catalyst_label} with the following properties: "
        )

        exclude_statement += ", ".join(exclude_list)
        exclude_statement += ". "
    else:
        exclude_statement = ""
    prompt = (
        f"Generate a list of candidate{catalyst_label} {candidate_list_statement}for "
        f"the adsorption of {adsorbate}. {include_statement}{exclude_statement}"
        "Let's think step-by-step and return a list of "
        f"top {num_answers} answers and their explanations as a list of pairs."
    )
    return prompt


def parse_answer(answer: str, num_expected=None):
    """Parse an answer into a list."""
    final_answer_location = answer.lower().find("final_answer")
    list_location = answer.find("[", final_answer_location)
    answer_list = answer[list_location + 1 : answer.find("]", list_location)]  # noqa
    answer_list = [ans.replace("'", "") for ans in answer_list.split(",")]
    return [ans.replace('"', "").strip() for ans in answer_list]


def init_openai():
    """Initialize connection to OpenAI."""
    openai.api_key = os.getenv("OPENAI_API_KEY_DEV")
    return


query_counter = 0
tok_sent = 0
tok_recieved = 0


@backoff.on_exception(backoff.expo, openai.error.OpenAIError, max_time=60)
def run_query(query, model="gpt-3.5-turbo", system_prompt=None, **gpt_kwargs):
    """Query language model for a list of k candidates."""
    gpt_kwargs["temperature"] = gpt_kwargs.get("temperature", 0.6)
    gpt_kwargs["top_p"] = gpt_kwargs.get("top_p", 1.0)
    gpt_kwargs["max_tokens"] = gpt_kwargs.get("max_tokens", 1300)
    now = datetime.datetime.now()
    logging.info(f"New query at time: {now}")

    # output = openai.Completion.create(
    #     model="text-davinci-003", max_tokens=1300, temperature=1, prompt=query
    # )

    if model == "text-davinci-003":
        output = openai.Completion.create(model=model, prompt=query, **gpt_kwargs)
        answer = output["choices"][0]["text"]
    elif "gpt-3.5" in model or "gpt-4" in model:
        if system_prompt is not None:
            messages = [{"role": "system", "content": system_prompt}]
        else:
            messages = []
        messages.append({"role": "user", "content": query})
        output = openai.ChatCompletion.create(
            model=model, messages=messages, **gpt_kwargs
        )
        print(output)
        answer = output["choices"][0]["message"]["content"]

    logging.info(f"--------------------\nQ: {query}\n--------------------")

    global query_counter
    query_counter += 1
    logging.info(f"Num queries run: {query_counter}")

    global tok_sent
    tok_sent += output["usage"]["prompt_tokens"]
    logging.info(f"Total num tok sent: {tok_sent}")

    now = datetime.datetime.now()
    logging.info(f"Answer recieved at time: {now}")

    logging.info(f"--------------------\nA: {answer}\n--------------------")

    global tok_recieved
    tok_recieved += output["usage"]["completion_tokens"]
    logging.info(f"Total num tok recieved: {tok_recieved}\n\n")

    return answer


def run_embedding_test():
    """Test embedding with language model."""
    str1 = "platinum"
    str2 = "cobalt"
    str3 = "wood"
    emb1 = get_embedding(str1)
    emb2 = get_embedding(str2)
    emb3 = get_embedding(str3)
    print(f"Cosine sim({str1}, {str2}): {cosine_similarity(emb1, emb2)}")
    print(f"Cosine sim({str1}, {str3}): {cosine_similarity(emb1, emb3)}")
    return


init_openai()
