# Security

ChainLog reads logs the operator already has and writes a case on the same machine. Secrets are redacted before a case is stored. ChainLog does not connect to a validator signer and does not store keys.

A remote model stays off unless that invocation passes `--remote`. The remote payload is the redacted case excerpts, not the raw log files.

Report a vulnerability through [GitHub private vulnerability reporting](https://github.com/ehsanhajian/chainlog/security/advisories/new).
