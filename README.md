# Anomaly Detection in LLM Agent Systems

## What is an anomaly?

Any unexpected behavior or pattern that deviates from normal operating conditions when multiple agents interact (including things like hallucinations, conflicting actions, protocol breakdowns, etc.). The key challenge is combinatorial complexity, as you add agents, interaction patterns explode, and “normal” behavior depends on what other agents are doing.

Anything that the system does “out of the ordinary” is an anomaly to us. Our job should be able to detect that with precision and as fast as possible. There’s two routes we could go to decide what’s normal and what’s not: 1. We either set it up before the agentic system is run and we have some policies or rulesets that the system must follow, or 2. We’ve already run the system and have enough data that act as baselines and then any deviation from that is an anomaly.

I’ve gone through a number of papers and articles on this topic and consolidated my learnings and opinions here.

## How do we architect systems to set them up for anomaly detection?

A widely adopted method in the academic literature is to formalize the multi-agent system as a graph structure. Concretely, the system is represented by a dynamic directed graph, denoted as:

$$
G = (V, E)
$$

where each node `v` corresponds to an agent, a tool, or a message channel, and each edge `e` encodes a temporal or causal interaction (e.g., message passing, task delegation, or tool invocation).

There are two primary approaches for representing such a system as a graph:

1. An **utterance graph** is a graph whose primary “event” is an agent utterance (a message or chunk of dialogue), and whose semantics live mostly in text. Nodes typically correspond to agents, and edges represent communication or discourse influence between agents. The graph is often built per round or per dialogue step, and then the node and edge attributes are text-derived embeddings. [G-Safeguard](https://aclanthology.org/2025.acl-long.359.pdf#:~:text=4.3%20Scalability%20of%20G,using%20data%20generated%20from%20an) is a an example. It constructs a multi-agent utterance graph per interaction round where node embeddings come from an agent’s utterance plus its historical utterances, and edge embeddings come from the interaction history between two agents distilled via a fusion function.

In this framing, the “graph” is mostly about who influenced whom in conversation, plus semantic drift and propagation.

1. A **call graph** is a graph whose primary “event” is an execution step, such as an LLM invocation, tool call, function execution, retriever call, memory read/write, or sub-agent delegation. Nodes are usually functions, tools, agent modules, or model calls, and edges represent invocation, control flow, and data flow. This representation is common in observability and agent tracing systems, because it aligns with runtime spans and tool invocations.

[SentinelAgent](https://arxiv.org/pdf/2505.24201v1) uses a graph-based modeling of multi-agent execution and discusses monitoring nodes and edges over execution, including tool-call sequences and failure attribution along attack paths.

| Property | Utterance graph | Call graph |
| --- | --- | --- |
| Primary unit of structure | Dialogue content, utterances are the core signal | Execution events, calls are the core signal |
| What nodes represent | Usually agents, sometimes agent-utterance nodes depending on construction | Tools, functions, agents-as-modules, LLM invocations, retriever/memory ops, sub-agent modules |
| What edges represent | Communication or discourse influence, agent i sends message to agent j, sometimes aggregated over a round | Invocation, control flow, and data flow, agent calls tool, tool returns to agent, orchestrator calls sub-agent |
| Edge direction semantics | Speaker to listener, influence flow | Caller to callee, dependency flow |
| Edge multiplicity handling | Often fused into a single edge per agent pair per round, with edge features summarizing history | Many edges per run, each call is an edge or span, preserved as event-level sequence |
| Node and edge attributes | Dominated by text-derived embeddings and interaction history embeddings (node utterance history, edge interaction history) | Dominated by runtime metadata (tool name, args schema, latency, retries, errors, token counts), plus optional text payloads |
| Temporal granularity | Round-based or turn-based snapshots, frequently constructed at dialogue boundaries | Streaming, naturally incremental as spans occur during execution |
| Typical detection cadence | End of round, classify or score after utterances exist | Continuous, can score pre-tool-call, post-call, or on partial traces |
| Best at detecting | Compromised speaker behavior, semantic drift, misinformation propagation through communication topology | Tool misuse, unusual control flow, abnormal execution trajectories, multi-step attack chains, performance anomalies |
| Failure localization | Identifies risky agents or agent pairs, often points to which agent is compromised | Identifies anomalous node, edge, and path segments in the execution chain |
| Remediation lever | Communication disruption or edge pruning between agents, isolating risky speaker nodes | Block or gate tool calls, alter routing, roll back actions, isolate sub-agents, circuit-breaker on abnormal paths |
| Data requirements for modeling | Requires message content, conversation structure, often designed for multi-agent chat settings | Requires runtime instrumentation and structured logs, tool schemas, execution traces |

## Kinds of Anomalies

### 1. Global Anomalies

These occur when the overall system output violates the user’s intent, task specification, or safety constraints.
They are observable only at the system boundary, after the full execution graph completes. Individual agent actions may appear reasonable in isolation, but the combined behavior is incorrect.

### Final Output ≠ Expected Output

This anomaly occurs when the terminal state of the system does not satisfy the task’s success criteria, even though intermediate states may have appeared correct.

Examples include:

- The system reaches a valid output at some point, but later agents overwrite or invalidate it.
- The task is partially completed but never finalized.
- The system produces a plausible but incorrect answer that violates the original specification.
- Deterministic workflows that historically converge correctly begin diverging across repeated executions without explicit prompt or code changes.

From a detection perspective, this could look like:

- Sudden drops in task completion rate across similar call graphs.
- Inconsistencies in terminal outputs for equivalent inputs.
- Violations of end-state invariants that previously held.

### Why might these anomalies occur?

These anomalies stem from flaws in how the multi-agent system is architected. While they surface during execution, their root cause lies in pre-execution design decisions.

Concrete failure modes identified in the literature:

- **FM-1.1 Disobey Task Specification**
The system produces an output that violates explicit task constraints or user intent. This often occurs when constraints are underspecified or not actively enforced, allowing agents to optimize for local goals instead of the global objective.
- **FM-1.2 Disobey Role Specification**
Agents act outside their assigned responsibilities, such as a reviewer generating new content or an executor redefining goals. This typically arises from ambiguous role definitions or lack of role enforcement in the workflow.
- **FM-1.3 Step Repetition**
The system loops over the same reasoning or execution steps without making progress. This is a structural failure caused by missing state transitions, unclear ownership of sub-tasks, or absent “done” criteria.
- **FM-1.4 Loss of Conversation History**
Critical context is dropped, truncated, or inconsistently summarized, causing agents to revert to earlier assumptions or redo completed work. This is a state management failure, not a reasoning failure.
- **FM-1.5 Unaware of Termination Conditions**
The system does not know when to stop. Agents continue executing despite having met the task requirements, or they stop prematurely without producing a final, validated output. This occurs when termination conditions are implicit, uncheckable, or not owned by any agent.

These failure modes frequently lead to global anomalies such as:

- Goal drift where the system’s final output no longer aligns with the original intent.
- Execution graphs that never converge to a stable terminal state.
- Outputs that are internally consistent but externally invalid.

These anomalies occur when the multi-agent system consumes abnormal amounts of compute, memory, latency, or API budget relative to its expected operational profile.

- Unbounded resource growth
Execution graphs that grow unexpectedly in depth or breadth, leading to excessive token usage, memory pressure, or API calls. Often caused by recursive agent calls, uncontrolled delegation, or missing termination checks.
- Latency spikes and tail amplification
Sudden increases in end-to-end latency, even when individual agent latencies appear normal. Coordination overhead, synchronization waits, or cascading retries can create long-tail delays at the system level.
- Hotspot agents
Certain agents or workflow stages disproportionately consume compute or time compared to historical executions. This frequently indicates role leakage, step repetition, or agents performing unintended work.
- Throughput degradation under stable load
The system processes fewer tasks per unit time despite similar input volume. This can signal hidden loops, increased internal chatter between agents, or degraded scheduling efficiency.
- Cost anomalies
Sharp deviations in token usage, API spend, or hardware utilization without a corresponding increase in task complexity. These are treated as first-class anomalies because they often surface before correctness failures.

### 2. Single-point Failures

Single-point failures are cases where one fragile component, a prompt, a tool boundary, or one agent’s decision, can compromise the entire multi-agent run. Most items below are not anomalies by themselves, they are **preconditions**.

### Prompt-level Vulnerabilities

Prompt issues are exposure surfaces. They matter because they make the system easier to push off-spec, but they only become anomalies when they cause role noncompliance or goal drift during execution.

- **Underspecification**: Missing constraints or boundaries.
- **Precedence ambiguity**: No clear hierarchy between task instructions, safety constraints, and formatting rules.
- **Drift across turns**: Summaries, truncation, or prompt reconstruction subtly changes intent.
- **Intermediate prompt contamination**: One agent’s output becomes another agent’s prompt.
- **Planner brittleness**: A flawed orchestrator prompt coordinates the system into a wrong trajectory.

### Tool Misuse

The misuse is usually detectable at the tool boundary, the anomaly is the bad trajectory it triggers.

- **Wrong tool or wrong mode**: Using generation instead of verification, or action instead of read-only.
- **Invalid or unsafe arguments**: Malformed inputs, stale state, or out-of-distribution parameters that return plausible but incorrect outputs.
- **Unvalidated tool outputs**: Treating tool results as ground truth without checks.
- **Runaway calling**: Missing stopping criteria causes repeated invocations and cost or latency spikes.

### Behavioral

Behavioral issues are best framed as stability risks unless they show up as consistent deviations across runs. They become anomalies when you can attach measurable drift or variance to a specific component.

- **Policy drift**: Role interpretation shifts over time due to memory or context reconstruction.
- **Inconsistent decisions**: Similar inputs lead to different actions or tool choices.
- **Silent rule violations**: Constraints are violated without any local error signal.
- **Implementation bugs**: Orchestration or parsing faults misread as model “reasoning errors.”

Detection could look like:

- A sudden behavior shift without prompt or state changes.
- High variance tied to one agent or one tool edge.
- Failures that disappear when a single step is gated or bypassed.

### 3. Multi-point distributed failures

Multi-point failures are anomalies that emerge from the interaction structure, not from a single bad step. The core signal is cross-agent dynamics, for example misalignment propagation, coordination feedback loops, and multi-hop execution chains that bypass single-agent input-output checks.

### Agent coordination

Coordination risk is framed as failures that arise from delegation, role distribution, and shared memory interacting in ways that create feedback loops, cascading misalignments, and emergent collusion. 

- **Feedback loops and decision amplification**: repeated cross-agent reinforcement of a bad plan or mistaken intermediate state.
- **Multi-hop attack chains**: benign-looking steps that become unsafe only when composed into a longer trajectory, which SentinelAgent analyzes as risky paths through the interaction graph.
- **Coordination failures that are not localizable**: no single step violates policy in isolation, but the composed chain violates task or safety constraints.

### Inter-agent misalignment

Breakdowns in critical information flow and mutual understanding during execution, leading to patterns like ignoring other agents’ input, withholding crucial information, proceeding on wrong assumptions instead of clarifying, conversation reset, task derailment, and reasoning-action mismatch.

- **Ignored input and information withholding**: the system loses necessary shared context, so downstream actions become inconsistent or incomplete.
- **Wrong assumptions instead of clarification**: agents proceed without resolving uncertainty.
- **Reasoning-action mismatch across agents**: agents’ stated plans do not match their executed steps, creating distributed inconsistencies that accumulate.

### Communication anomalies

Communication is both a vulnerability surface and an early warning channel. G-Safeguard emphasizes that malicious or misleading utterances can propagate from a small initial subset of agents into a larger compromised set over rounds.

- **Propagation patterns**: growing sets of affected agents across rounds, consistent with the cascading infection framing in G-Safeguard.
- **Edge-level risk signals**: anomalous inter-agent exchanges, adversarial message passing, or unintended control flow that SentinelAgent models as risky edge status and high-risk paths.
- **Message storms, deadlocks, protocol violations, content inconsistencies**

## How to Solve

The core challenge is that no single detection method catches everything. Different anomalies require different timing, different data, and different ways to respond. Some anomalies only show up when you look at who’s talking to whom. Others only appear when you trace tool calls. Some need to be caught before they execute. Others can only be detected after a full round completes.

### Build two graphs from the same trace stream

Every multi-agent run generates execution events: traces, spans, messages, tool calls, memory operations. We normalize these into a common schema, then build two different graph representations from the same stream.

**The utterance graph** treats agents as nodes and messages as edges. It captures who influenced whom through conversation. Node features come from what the agent said (text embeddings of utterances). Edge features come from interaction history between agent pairs. This graph is best at detecting semantic drift, agents spreading bad information, and cases where one compromised agent contaminates others through conversation.

**The call graph** treats function calls, tool invocations, and LLM calls as nodes, with edges representing control flow and data dependencies. It captures what actually executed at runtime. This graph is best at detecting tool misuse, unusual execution paths, resource spikes, and multi-step attack chains where each individual step looks fine but the sequence is risky.

We build both because they catch different things. The utterance graph catches influence propagation through dialogue. The call graph catches problems at the execution boundary. Together, they let us pinpoint both *who* is misbehaving and *what* went wrong.

From these graphs, we extract three kinds of features:

- **Structural**: node types, edge types, common patterns (motifs), and path signatures. This tells us if the execution or conversation structure looks normal.
- **Semantic**: text embeddings for utterances, tool arguments, and prompts. This tells us if the *content* has drifted.
- **Operational**: latency, cost, retries, fan-out. This tells us if performance or resource usage is abnormal.

We store snapshots: live state that updates incrementally as the run progresses, and checkpoint snapshots at maybe episode boundaries. At the center of the system is a **risk state** that tracks three things for each run:

1. **Likelihood**: How abnormal is this compared to baseline?
2. **Localization**: Which node, edge, or path is responsible?
3. **Imminence**: Is something unsafe about to happen right now?

**1. Baseline comparator** (uses both graphs, runs on checkpoints)

Compares current graph snapshots to historical normal runs using embeddings and structural metrics. Flags outliers and provides nearest-neighbor explanations. [Constrastive learning](https://www.v7labs.com/blog/contrastive-learning-guide) is something that can be used here.

**2. Utterance graph GNN** (uses utterance graph, runs per round)

A graph neural network that classifies per-agent risk at each dialogue round. Uses node embeddings (agent utterances + history) and edge embeddings (interaction history between agents).

**3. Call graph path** (uses call graph, runs continuously)

Watches for unusual tool call sequences, risky multi-hop paths, and unexpected control flow as they form. This catches execution anomalies like tool misuse, unintended function chains, and attack paths that only become unsafe when multiple steps combine.

**4. Action gate** (inline verification, runs before every high-impact action)

Sits at the boundary where actions become expensive or dangerous (tool calls, writes, transactions). Checks proposed actions against explicit rules and current risk state. Blocks, delays, or requires extra checks if something looks wrong. This is the only true preemption layer.

### Add LLM-as-a-judge?

Statistical detectors and graph patterns don’t catch everything. Sometimes you need semantic reasoning. Some literature uses LLM-as-a-judge in two distinct ways:

**Runtime audit (online, conditional)**

When the risk state crosses a threshold or an action is high-impact but ambiguous, we invoke an LLM to inspect the suspicious node, edge, or path. It produces a verdict with a natural language explanation and updates the risk state. This only runs when the other detectors are uncertain.

**Labeling (offline, every run)**

After a run completes, we feed the full trace and any anomaly reports to an LLM with a few-shot prompted taxonomy of failure modes. It labels what went wrong and why. These labels feed back into training data for the GNN, threshold calibration for the baseline comparator, and attack path libraries for the call graph monitor.

The hypothesis is simple: **you can’t solve multi-agent anomaly detection with a single model or a single graph.** You need multiple detection methods running on parallel graph representations, feeding a shared risk state, with both preemption and recovery. And you need a feedback loop where every detected anomaly becomes training data.