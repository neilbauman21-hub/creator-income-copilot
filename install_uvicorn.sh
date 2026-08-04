#!/bin/bash
# Install uvicorn into the project venv
cd ~/creator-income-copilot
.venv/bin/pip install -q uvicorn
.venv/bin/python -c "import uvicorn; print('uvicorn OK')"
