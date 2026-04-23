"""Compatibility wrapper around the vendored UUPM core module."""
from .vendor import load_uupm_modules

_CORE_MODULE, _, _ = load_uupm_modules()

DATA_DIR = _CORE_MODULE.DATA_DIR
MAX_RESULTS = _CORE_MODULE.MAX_RESULTS
CSV_CONFIG = _CORE_MODULE.CSV_CONFIG
STACK_CONFIG = _CORE_MODULE.STACK_CONFIG
AVAILABLE_STACKS = _CORE_MODULE.AVAILABLE_STACKS
BM25 = _CORE_MODULE.BM25
detect_domain = _CORE_MODULE.detect_domain
search = _CORE_MODULE.search
search_stack = _CORE_MODULE.search_stack
