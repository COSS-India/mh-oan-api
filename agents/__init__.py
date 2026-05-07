import logfire
from dotenv import load_dotenv

from helpers.otel_env import normalize_otlp_endpoint_env

load_dotenv()
normalize_otlp_endpoint_env()

logfire.configure(scrubbing=False)