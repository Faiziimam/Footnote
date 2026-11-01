#!/bin/bash
# Double-click on Mac (or run on Linux). Opens the tracker for the folder this file is in.
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
python3 -m footnote --project "$PWD" ui
