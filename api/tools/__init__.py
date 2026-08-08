"""Build-time tools for the edge. Not imported by the running service.

A package rather than loose scripts because the tests import them
(`from tools.generate_dtos import render`), and without this mypy sees each
file under two module names and refuses to check anything.
"""
