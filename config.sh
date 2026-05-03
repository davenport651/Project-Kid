#!/bin/bash

# Activate virtual environment if it exists
if [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"
fi

# Run the configurator
python3 "Chronopolis/configurator.py" "$@"
