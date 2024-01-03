"""Functions for running azync azure openai prompts."""
import asyncio
import os

from typing import Union

from dotenv import load_dotenv
from openai import AsyncAzureOpenAI


def init_azure_openai(model):
    """Initialize connection to OpenAI."""
    load_dotenv()
    client = AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    )
    return client


async def parallel_azure_openai_chat_completion(
    client, prompt, system_prompt=None, model="gpt-3.5-turbo", **kwargs
):
    """Run chat completion calls on openai, in parallel."""
    messages = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return await client.chat.completions.create(
        messages=messages, model=model, **kwargs
    )


async def azure_openai_chat_async_evaluation(
    client, prompts, system_prompts, model="gpt-3.5-turbo", **kwargs
):
    completions = [
        parallel_azure_openai_chat_completion(client, p, s, **kwargs)
        for p, s in zip(prompts, system_prompts)
    ]

    answers = await asyncio.gather(*completions)
    return answers


def run_openai_prompts(
    prompts: list[str],
    system_prompts: list[Union[str, None]] = None,
    model="gpt-3.5-turbo",
    **kwargs
):
    """Run the given prompts with the openai interface."""
    client = init_azure_openai(model)
    # Apply defaults to kwargs
    kwargs["temperature"] = kwargs.get("temperature", 0.6)
    kwargs["top_p"] = kwargs.get("top_p", 0.3)
    kwargs["max_tokens"] = kwargs.get("max_tokens", 1300)

    if system_prompts is None:
        system_prompts = [None] * len(prompts)

    if model == "text-davinci-003":
        pass

    elif "gpt-3.5" in model or "gpt-4" in model:
        answer_objects = asyncio.run(
            azure_openai_chat_async_evaluation(
                client,
                prompts,
                system_prompts=system_prompts,
                model=model,
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
        return [{"answers": a, "usages": u} for a, u in zip(answer_strings, usages)]


if __name__ == "__main__":
    run_openai_prompts(["test prompt", "test 2"], ["sys1", "sys2"])
