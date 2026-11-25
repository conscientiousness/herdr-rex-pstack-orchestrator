#!/usr/bin/env python3
import sys
from importlib import import_module

agent_workers = import_module("agent-workers")

if __name__ == "__main__":
    agent_workers.cli()
else:
    sys.modules[__name__] = agent_workers
