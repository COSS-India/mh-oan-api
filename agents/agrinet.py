import os
from pydantic_ai import Agent, RunContext
from helpers.utils import get_prompt, get_today_date_str, get_crop_season
from agents.models import AGRINET_MODEL
from agents.tools import TOOLS
from pydantic_ai.settings import ModelSettings
from agents.deps import FarmerContext
from dotenv import load_dotenv
load_dotenv()

# ── Model-compatibility toggles (defaults preserve original OAN behavior) ──────
# Needed for limited model servers (e.g. gemma) that lack tool-calling, have a
# small context window, or reject large output requests. Leave unset / defaulted
# for the full agrinet/Qwen model. See OAN_HOSTING_PLAN.md.
#   AGRINET_DISABLE_TOOLS=true        -> don't send tools (default: tools enabled)
#   AGRINET_MAX_TOKENS=<n>            -> output cap (default: 32768)
#   AGRINET_PROMPT_MAX_CHARS=<n>      -> trim system prompt to n chars (default: 0 = full)
_DISABLE_TOOLS = os.getenv("AGRINET_DISABLE_TOOLS", "false").lower() in {"1", "true", "yes"}

_AGRINET_MODEL_SETTINGS = ModelSettings(
    max_tokens=int(os.getenv("AGRINET_MAX_TOKENS", "32768")),
    parallel_tool_calls=True,
    request_limit=10,
)

agrinet_agent = Agent(
    model=AGRINET_MODEL,
    name="Vistaar Agent",
    instrument=True,
    output_type=str,
    deps_type=FarmerContext,
    retries=3,
    tools=[] if _DISABLE_TOOLS else TOOLS,
    end_strategy="exhaustive",
    model_settings=_AGRINET_MODEL_SETTINGS,
)

@agrinet_agent.system_prompt(dynamic=True)
def get_agrinet_system_prompt(ctx: RunContext[FarmerContext]):
    lang_code = ctx.deps.lang_code or "en"
    prompt_name = f"agrinet_system_{lang_code}"
    prompt = get_prompt(prompt_name, context={
        "today_date": get_today_date_str(),
        "crop_season": get_crop_season(),
    })
    # Trim only when a cap is set (gemma's 4096-token window); 0 = full prompt.
    cap = int(os.getenv("AGRINET_PROMPT_MAX_CHARS", "0"))
    return prompt[:cap] if cap > 0 else prompt