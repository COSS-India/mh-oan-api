import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models import ModelSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from evaluation.schemas import EvalCase, ResponseJudgeResult
from helpers.utils import get_prompt

load_dotenv()

PROMPT_DIR = str(Path(__file__).parent / "prompts")

judge_agent = Agent(
    model=OpenAIChatModel(
        os.getenv("EVAL_JUDGE_MODEL_NAME", "gpt-5"),
        provider=OpenAIProvider(
            openai_client=AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")),
        ),
    ),
    name="Response Judge",
    system_prompt=get_prompt("judge_system", prompt_dir=PROMPT_DIR),
    output_type=PromptedOutput(ResponseJudgeResult),
    retries=2,
    instrument=False,
    model_settings=ModelSettings(request_limit=3),
)


async def judge_response(case: EvalCase) -> ResponseJudgeResult:
    prompt = (
        f"source_lang: {case.source_lang}\n"
        f"target_lang: {case.target_lang}\n\n"
        f"Query:\n{case.query}\n\n"
        f"Response:\n{case.response}"
    )
    result = await judge_agent.run(prompt)
    return result.output
