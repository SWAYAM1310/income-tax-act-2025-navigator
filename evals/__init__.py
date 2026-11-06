"""The eval harness. Importing it turns LangSmith tracing off for the whole process: a full dev
run is 138 traces against a 5K/month free allowance. Forced rather than defaulted, because VS
Code's `python.terminal.useEnvFile` puts `.env` into the shell, where a default would lose."""

import os

os.environ["LANGSMITH_TRACING"] = "false"
