# scarlet-agentic-harness

A generalized decentralized agentic **Skill** harness built on top of this
repo's `scarlets` primitives (`Mapper`, `Federator`, `Messenger`) — deployed
alongside [Gustavo](https://github.com/disys-lab/gustavo) as
`ghcr.io/disys-lab/scarlet-agents`.

Full docs, including build history, design decisions, and deployment
instructions, now live in this repo's MkDocs site:
[docs/harness/](../docs/harness/index.md) (or the hosted site's **Harness**
nav section).

Quick start for running the tests:

```bash
cd harness/
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -r requirements.txt
python3 -m pytest tests/ -v
```
