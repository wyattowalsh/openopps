## ADDED Requirements

### Requirement: Free static delivery is proven on the full corpus

OpenOpps SHALL accept Workers Static Assets only after the final dual-release corpus succeeds on Workers Free with assets-only configuration, full hash verification, atomic promotion, rollback, and re-promotion.

#### Scenario: An undocumented aggregate limit rejects the corpus

- **WHEN** the final upload cannot complete or verify
- **THEN** cutover stops
- **AND** no metered fallback is activated without a new decision

### Requirement: Publication inputs are immutable and independently verifiable

Kaggle and public-data publication SHALL use immutable source/tool inputs, recompute canonical roots, and record exact-version readback evidence.

#### Scenario: Manifest and files are substituted together

- **WHEN** verification recomputes the root
- **THEN** substitution fails unless the external expected digest and exact set match

### Requirement: Local and remote assurance contracts agree

Required CI gates SHALL have canonical local recipes with pinned tooling, timeouts, least privilege, supported-runtime matrices, audits, and evidence artifacts.

#### Scenario: Exact-SHA release evidence is incomplete

- **WHEN** local gates pass but origin CI, deployment, or production smoke is absent
- **THEN** the change remains incomplete
- **AND** production readiness is not claimed

### Requirement: History rewriting is separately authorized

OpenOpps SHALL remove generated production data ordinarily after cutover and SHALL rewrite history only after separate approval, ref inventory, protected backup, SHA mapping, fresh-clone validation, and recovery instructions.

#### Scenario: Force-push approval is absent

- **WHEN** preparation passes but explicit authority is missing
- **THEN** no rewrite or force-push executes
