# 2. No runtime dependencies

Status: accepted

## Decision
The package uses only the Python standard library. A test (`CodeAndSupplyChain`) fails if a third-party import appears.

## Why
Every dependency is code we do not control that runs with the user's access to their project and tokens. Supply-chain attacks on
packages are among the most common real-world compromises. It also makes the one-file installer (`footnote.pyz`) trivial and
reproducible, and keeps install friction near zero for non-developers.

## Consequences
We write small things ourselves (a PowerPoint writer, an HTTP client wrapper, a markdown converter). Optional extras for developers
(`python-pptx` to double-check decks, `bandit`) are used only in tests/CI, never at runtime.
