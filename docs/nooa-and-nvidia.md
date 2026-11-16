# NOOA fit and NVIDIA integration map

Assessment date: 2026-11-16. Repository/API examples were inspected during authoring;
dependencies were not installed and compatibility was not executed. Current `main`
may evolve. Pin reviewed versions when preparing the remote environment.

## Is NOOA a good fit?

**Yes, as one harness under evaluation.** Python objects, typed generation methods,
deterministic methods, state, and framework traces fit a stateful service-desk agent.
Using a narrow typed action adapter lets us swap harnesses without moving permission
enforcement or evaluation criteria into the harness itself.

The implemented `NooaBackend` follows the upstream structured-output and tracing
examples. It creates an `Agent`, uses `PredictStrategy` for `next_action`, selects
an LLM through the configured NOOA alias, and enables an explicit journal exporter.
The application then executes the action. This is a real optional NOOA dependency,
not an alias around the direct Chat Completions adapter.

This intentionally does not exercise NOOA CodeAct, its own long-term memory plugin,
or its full benchmark runner. Consequently it establishes an experiment surface for
NOOA, not a benchmark of every NOOA capability. A later CodeAct comparison can expose
the same World methods to an agent object, but needs OS-level containment and trace
normalization. Upstream describes generated-code guardrails as defense in depth,
not a sandbox boundary.

NOOA does not supply the complete population calibration, paired experiment,
production router, or cross-version memory migration protocol required by the
original architecture. Keep those application-owned so the experiment can compare
NOOA with other harnesses fairly.

## Implemented versus extension paths

| Component | Status here | Role in the larger architecture |
|---|---|---|
| Core sampler and behavioral state machine | Implemented | Reproducible fictional users, goals, corrections, clarification and abandonment |
| Direct Chat Completions adapter | Implemented; unexecuted | A comparison harness for an actual compatible model endpoint |
| NOOA typed planner and native journal | Implemented; optional, unexecuted | Swappable candidate/baseline execution layer |
| Data Designer enrichment | Implemented; optional, unexecuted | Linguistic variation of validated scenario seeds |
| NeMo User Sim / Nemotron-Personas | Extension path, no SDK claim | Richer population-grounded user interactions; enterprise-role calibration still needed |
| NeMo Gym | Extension path, no SDK claim | Environment rollout execution, verifiers, and scenario evaluation |
| Agent Memory datasets/evaluation work | Design influence; no internal runtime dependency | Memory-dependent tasks, environments, verifiers, dataset quality and provenance |
| NeMo Relay | Extension path, no exporter claim | Runtime interception/observability and normalized trace export |
| NeMo Helix | Extension path, no API integration claim | Repeatable evaluation/optimization/hardening orchestration |
| NeMo Fabric | Extension path, no adapter claim | Common harness execution interfaces |
| Local experiment controller | Implemented | Simulated tenant routing, session continuity, audit and rollback |

The simple scoped Memory class is owned by this lab. It is not an implementation
of NeMo Agent Memory, a drop-in enterprise knowledge ingestion service, or a claim
about NOOA MemoryManager's API. This separation preserves experimental control.

## Public sources

- [NOOA repository and installation/platform guidance](https://github.com/NVIDIA-NeMo/labs-OO-Agents)
- [NOOA structured generation example](https://github.com/NVIDIA-NeMo/labs-OO-Agents/blob/main/examples/quickstart/02_structured_outputs.py)
- [NOOA deterministic tool methods example](https://github.com/NVIDIA-NeMo/labs-OO-Agents/blob/main/examples/quickstart/03_codeact_tools.py)
- [NOOA durable tracing example](https://github.com/NVIDIA-NeMo/labs-OO-Agents/blob/main/examples/quickstart/06_tracing.py)
- [NOOA package metadata and Python requirement](https://github.com/NVIDIA-NeMo/labs-OO-Agents/blob/main/pyproject.toml)
- [Data Designer API overview](https://github.com/NVIDIA-NeMo/DataDesigner)
- [Data Designer preview API source](https://github.com/NVIDIA-NeMo/DataDesigner/blob/main/packages/data-designer/src/data_designer/interface/data_designer.py)
- [NeMo User Sim](https://github.com/NVIDIA-NeMo/UserSim)
- [Gym User Sim rollout tutorial](https://docs.nvidia.com/nemo/gym/tutorials/evaluation-tutorials/nemo-user-sim-rollout-collection)
- [Agent Toolkit migration guide: Relay, Helix, and Fabric](https://docs.nvidia.com/nemo/agent-toolkit/latest/resources/migration-guide.html)

The Agent Toolkit migration guide states that NeMo Agent Toolkit was deprecated in
October 2026 with end of life at year end. This project therefore avoids introducing
a new dependency on that toolkit. Upstream NOOA recommends Linux/WSL 2; native
Windows is not its supported full runtime target.

## Next experiment after a remote run

First compare rules against rules to inspect artifacts, then compare direct-model
planning against NOOA with the same model, policy, scenario inputs, and initial
memory. Separately compare cold and migrated memory. Only after that change the
model or memory backend. This distinguishes harness effects from memory/model effects.
Add a User Sim domain once the basic environment and verifier behavior are understood.
