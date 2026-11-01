# 4. The project is licensed under Apache-2.0

Status: accepted

## Context
We want wide adoption by individuals and companies, and we do not plan to patent the idea (software patents are costly, narrow and
weak for this kind of tool, and publishing code can forfeit patent rights in many countries).

## Decision
Release under the **Apache License 2.0**. The copyright stays with the project's maintainers. Protect the *name* with a trademark rather
than a patent (the licence deliberately grants no trademark rights, section 6; see `NOTICE`). Contributors sign off commits (DCO).

## Why Apache-2.0 and not MIT
Same freedoms, plus an explicit patent grant from every contributor and patent-retaliation protection, which makes companies more
comfortable adopting and contributing. Copyleft licences (GPL/AGPL) were rejected because the product runs on the user's own device
(ADR 0001), so there is no hosted competitor to guard against, and strong copyleft would slow adoption.

## Consequences
- Anyone may use, modify, embed and sell the code, including in closed products; they may not use the Footnote name or logo.
- Because all copyright is currently held by the maintainers, the licence of *future* versions can still be changed. Once outside
  contributions are accepted that needs their consent, so decide before opening to contributors whether a dual-licence or commercial
  path is ever wanted.
- Copyright in AI-generated code is unsettled in some countries; a short consultation with an IP lawyer is recommended before launch.
