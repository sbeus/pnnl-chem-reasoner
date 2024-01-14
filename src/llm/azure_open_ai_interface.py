"""Functions for running azync azure openai prompts."""
import asyncio
import logging
import os

from typing import Union

from dotenv import load_dotenv
from openai import AsyncAzureOpenAI, RateLimitError

logging.getLogger().setLevel(logging.INFO)


def init_azure_openai(model, dotenv_path):
    """Initialize connection to OpenAI."""
    load_dotenv(dotenv_path=dotenv_path)
    client = AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
    )
    logging.info(os.environ["AZURE_OPENAI_API_KEY"])
    return client


async def parallel_azure_openai_chat_completion(
    client, prompt, system_prompt=None, model="gpt-4", **kwargs
):
    """Run chat completion calls on openai, in parallel."""
    messages = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        return await client.chat.completions.create(
            messages=messages, model=model, **kwargs
        )
    except RateLimitError as err:
        error_message = str(err)
        logging.info(f"TIMING: Recieved RateLimitError {error_message}")
        if "Please retry after " in error_message:
            retry_time = float(
                error_message.split("Please retry after ")[-1].split(" seconds")[0]
            )
            await asyncio.sleep(retry_time)
        else:
            await asyncio.sleep(60)

        return await parallel_azure_openai_chat_completion(
            client=client,
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            **kwargs,
        )


async def azure_openai_chat_async_evaluation(
    client, prompts, system_prompts, model="gpt-4", **kwargs
):
    completions = [
        parallel_azure_openai_chat_completion(client, p, s, **kwargs)
        for p, s in zip(prompts, system_prompts)
    ]

    answers = await asyncio.gather(*completions)
    return answers


class AzureOpenaiInterface:
    """A class to handle comminicating with Azuer openai."""

    def __init__(self, dotenv_path=str, model="gpt-4"):
        """Load the client for the given dotenv path."""
        self.dotenv_path = dotenv_path
        self.model = model

    def __call__(
        self,
        prompts: list[str],
        system_prompts: list[Union[str, None]] = None,
        **kwargs,
    ):
        """Run the given prompts with the openai interface."""
        client = init_azure_openai(self.model, self.dotenv_path)
        # Apply defaults to kwargs
        kwargs["temperature"] = kwargs.get("temperature", 0.7)
        kwargs["top_p"] = kwargs.get("top_p", 0.95)
        kwargs["max_tokens"] = kwargs.get("max_tokens", 800)

        if system_prompts is None:
            system_prompts = [None] * len(prompts)

        answer_objects = asyncio.run(
            azure_openai_chat_async_evaluation(
                client,
                prompts,
                system_prompts=system_prompts,
                model=self.model,
                **kwargs,
            )
        )
        answer_strings = [a.choices[0].message.content for a in answer_objects]
        usages = [
            {
                "completion_tokens": a.usage.completion_tokens,
                "prompt_tokens": a.usage.prompt_tokens,
            }
            for a in answer_objects
        ]
        return [{"answer": a, "usage": u} for a, u in zip(answer_strings, usages)]


if __name__ == "__main__":
    run_azure_openai_prompts(["test prompt", "test 2"], ["sys1", "sys2"])
