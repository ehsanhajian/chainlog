# ChainLog

ChainLog answers one question: **why did my infrastructure fail?**

It reads the logs an operator already has — execution clients, consensus clients, validators, and Kubernetes — and returns a cause that cites those lines. The case stays on the machine. A model is optional, and it only sees redacted excerpts.

ChainLog does not restart a client, edit a manifest, scrape a cluster, or sign with a validator key.

Work is tracked in [milestones](https://github.com/ehsanhajian/chainlog/milestones). This tree is the 0.1.0 shell: `chainlog --version` is the command that exists today.

## Command

| Question | Command |
| --- | --- |
| Read logs into a local case | `ingest` |
| Which failure classes are present? | `classify` |
| What happened, in order? | `timeline` |
| Why did it fail? | `why` |
| Has this happened before? | `patterns` |
| What should I check next? | `ask` |
| Write the report | `report` |

`why` can take a case id, or the same files as `ingest`. It classifies, builds the timeline, and states a cause.

```bash
chainlog ingest \
  --execution /var/log/geth/geth.log \
  --consensus /var/log/lighthouse/beacon.log \
  --validator /var/log/lighthouse/validator.log \
  --builder /var/log/mev-boost.log \
  --kube /tmp/events.json

chainlog why --case 20261008T061200Z
chainlog ask --case 20261008T061200Z "what happened in the slot before the miss?"
chainlog report --case 20261008T061200Z
```

Exit 0 means a cause is stated and every claim cites a timeline row. Exit 1 means the evidence is not enough. Exit 3 is a usage error or an unreadable input.

## What a cause is allowed to say

A cause cites timeline rows: time, source, and the redacted line. The report separates three things:

- **Trigger** — the earliest cited class that explains what followed.
- **Contributors** — cited conditions that made it worse, such as disk pressure before a database error.
- **Symptoms** — later misses, restarts, or probe failures that the trigger explains.

A symptom is never printed as the trigger. A class is applied only when a catalog rule matches, and every rule has a source. An unmatched line stays unclassified. When the lines do not support a cause, `why` says so and names what is missing.

A doppelganger detection or a slashable duty is printed first, even when an earlier warning exists in the window.

## Sources

| Source | Clients and objects | What it explains |
| --- | --- | --- |
| Execution | Geth, Nethermind, Erigon, Besu, Reth | Sync, database, engine API, peers, disk, JWT |
| Consensus | Lighthouse, Prysm, Teku, Nimbus, Lodestar | Slots, fork choice, checkpoints, engine calls |
| Validator | Validator clients, Web3Signer | Missed duties, doppelganger, signer timeouts |
| Builder | MEV-boost | Relay and builder timeouts on a proposal |
| Kubernetes | Container logs, cluster events | OOM, eviction, probes, volume mounts, node pressure |

Slot, epoch, and block are taken from the line that prints them. A slot filled in from a nearby consensus line is marked inferred. When two consensus lines disagree, the slot stays blank.

## Around the failure

An alert can open the case. A ValidatorPulse or Prometheus alert sets the window: one hour before it fired, and fifteen minutes after. A metric snapshot for that window can support a contributor: disk, memory, restarts, peer count, head lag, attestation effectiveness.

ChainLog reads the snapshot the operator exports. ValidatorPulse remains the monitor that raises the alert. ChainDiff remains the tool that decides whether a client upgrade is safe. ChainLog records the version change and stops there.

A pattern exported for another host contains class ids, client, version, and the order of classes. It contains no log lines and no host names.

## Where a case lives

Cases are written under `~/.chainlog`, or `CHAINLOG_HOME` when that is set. The case stores redacted excerpts and citations. The raw files stay at the paths the operator passed.

Redaction removes private keys, mnemonics, keystore passwords, JWT secrets, and API tokens before the case is written and before any model sees text. Validator pubkeys and peer ids stay, because the timeline joins on them. A removed span is marked.

`ask` answers from the case. With no model configured, it answers from the cause and the sourced runbook. `--remote` is off unless that invocation sets it, and the command prints that a remote call is about to happen. If redaction did not run, the remote call is refused.

## Report

`report` writes markdown and JSON: cause, trigger, contributors, symptoms, the last healthy slot, the first bad slot, citations, and the pattern note. `--no-paths` drops local file paths. `--bundle` writes the redacted citations, the signature, and a hash. `--verify` checks that hash later.

## Install

Python 3.11 or newer.

```bash
pip install -e ".[dev]"
chainlog --version
pytest
```

## Limits

ChainLog explains a failure from evidence the operator provides. It does not fetch logs from a cluster API, apply a fix, or decide that a release is safe to run.
