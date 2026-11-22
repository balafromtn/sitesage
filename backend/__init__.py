"""
SiteSage Backend Package.
Contains crawler, indexer, ranker, extractor, polisher, API, and pipeline modules.
"""

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
