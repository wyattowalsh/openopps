## ADDED Requirements

### Requirement: Public URLs are first-class job pull inputs

OpenOpps SHALL accept a public HTTPS ATS board URL, exact posting URL, or company careers URL through both the root URL shorthand and the explicit jobs pull command.

#### Scenario: User passes a URL at the root

- **WHEN** the user runs `openopps <URL>` with a supported public HTTPS URL
- **THEN** OpenOpps invokes the same URL-pull workflow as `openopps jobs pull <URL> --operation auto`
- **AND** it automatically resolves the provider and selects a board-list or exact-posting operation from the resolved target

#### Scenario: User selects a pull operation explicitly

- **WHEN** the user runs `openopps jobs pull <URL> --operation auto|list|get`
- **THEN** OpenOpps validates the requested operation against the resolved target and provider capabilities
- **AND** uses the same resolver, pull service, persistence policy, renderer, and failure contract used by the root URL shorthand

#### Scenario: Root input is not an eligible URL

- **WHEN** root input is a root option, help or version request, an existing command, an option value, a malformed URL, or an unknown non-URL command
- **THEN** URL shorthand dispatch does not consume or reinterpret that input
- **AND** existing root behavior and ordinary unknown-command exit behavior remain intact

### Requirement: URL pull controls have explicit bounded meanings

OpenOpps SHALL expose pull controls for direct matching, bounded discovery probes, board-scan fallback, unlisted membership, persistence, cache freshness, output, paging, quiet mode, and repeatable verbosity without weakening the public-HTTPS or transport-safety contract.

#### Scenario: User requires a direct ATS target

- **WHEN** the user supplies `--direct`
- **THEN** OpenOpps requires the input to match a natively supported ATS URL
- **AND** skips careers-page discovery while still permitting the requested supported ATS operation

#### Scenario: User disables provider slug probes

- **WHEN** the user supplies `--no-probe`
- **THEN** OpenOpps may still follow allowed redirects and inspect the one bounded careers page and its links
- **AND** does not perform provider-specific slug probes

#### Scenario: User disables board-scan fallback

- **WHEN** the user requests one posting with `--no-board-scan`
- **THEN** OpenOpps uses only a declared native exact-posting operation
- **AND** fails with the documented unsupported-operation result when no such operation exists

#### Scenario: User opts into unlisted board membership

- **WHEN** the user supplies the documented unlisted-inclusion option for a list pull
- **THEN** OpenOpps requests unlisted postings only when the provider explicitly declares and implements that capability
- **AND** otherwise reports the capability mismatch rather than implying expanded membership

#### Scenario: User requests an operationally ephemeral pull

- **WHEN** the user supplies `--no-save` or omits `--save`
- **THEN** the URL pull leaves operational board, route, job, version, lifecycle, and pull-audit records unchanged
- **AND** shared HTTP-cache behavior remains independently governed by cache controls

#### Scenario: User opts into persistence

- **WHEN** a URL pull succeeds with `--save`
- **THEN** OpenOpps persists a complete validated result to the reserved `url-pull` ledger
- **AND** persist failure exits 9 (`PERSISTENCE_FAILED`) rather than claiming a saved success
- **AND** it does not treat cache presence or cache writes as proof that operational records were saved

#### Scenario: User requires fresh transport results

- **WHEN** the user supplies `--refresh-cache`
- **THEN** the shared HTTP cache read is bypassed according to the existing refresh contract
- **AND** the URL pull continues to use the shared transport stack and its write policy

### Requirement: Provider URL capabilities are public and inspectable

OpenOpps SHALL expose `providers detect <URL>`, `providers inspect <URL>`, and `providers capabilities` as public read-only commands while retaining existing advanced provider commands.

#### Scenario: User detects a native provider URL

- **WHEN** the user runs `openopps providers detect <URL>`
- **THEN** output reports the deterministic provider and target classification when recognized
- **AND** includes parsed board and posting identifiers that are available from the URL

#### Scenario: User inspects URL resolution

- **WHEN** the user runs `openopps providers inspect <URL>`
- **THEN** output reports sanitized requested and resolved URLs, discovery method, provider, resolved operation, parsed identifiers, visited URLs, and probed slugs
- **AND** the command does not fetch job results, save operational records, or mutate the source catalog

#### Scenario: User inspects provider capabilities

- **WHEN** the user runs `openopps providers capabilities`
- **THEN** output distinguishes full-board list, native single-post get, board-scan get, detect-only, and unsupported states per provider
- **AND** distinguishes documented public interfaces from best-effort public interfaces
- **AND** identifies built-in versus plugin-provided capabilities

#### Scenario: Provider cannot perform a URL pull

- **WHEN** detection resolves to a detect-only or unsupported provider, or no provider is recognized
- **THEN** the public inspection commands report that state truthfully
- **AND** do not present the provider as successfully pull-capable

### Requirement: URL pull rendering is consistent across invocations

The root URL shorthand and `jobs pull` SHALL share one rendering contract that supports semantic terminal output, machine-readable output, atomic file output, and interactive paging.

#### Scenario: User relies on output defaults

- **WHEN** a successful URL pull writes to an interactive terminal without an explicit format
- **THEN** OpenOpps emits semantic Rich output
- **AND** when the same result is piped, OpenOpps emits normalized indented JSON instead

#### Scenario: User selects a format

- **WHEN** the user explicitly selects pretty, JSON, JSONL, or table output
- **THEN** both public URL-pull spellings honor that format with equivalent result semantics

#### Scenario: User writes pull output to a file

- **WHEN** the user selects an output path
- **THEN** OpenOpps writes the complete selected representation atomically
- **AND** does not leave a partial destination on rendering or write failure

#### Scenario: User requests paging

- **WHEN** the user requests paging for pretty output in an interactive terminal
- **THEN** OpenOpps may page the rendered result
- **AND** paging is not invoked for machine-readable output, non-interactive output, or file output

### Requirement: Raw URL pull output has a stable structured envelope

OpenOpps SHALL make `--raw` emit a stable structured envelope containing pull provenance and the provider-native structured payloads retained for each posting, without claiming lossless wire-response preservation.

#### Scenario: User requests raw output

- **WHEN** the user runs a successful URL pull with `--raw`
- **THEN** each posting includes its captured `listing` and `detail` payload fields plus sanitized pull provenance
- **AND** unavailable listing or detail payload fields remain explicitly representable
- **AND** normal output continues to use the normalized OpenOpps job contract

#### Scenario: Raw output is machine-readable

- **WHEN** the user combines `--raw` with JSON or JSONL output
- **THEN** stdout contains only the documented raw envelope representation
- **AND** the output remains parseable without scraping terminal text

### Requirement: URL pull diagnostics never corrupt result output

OpenOpps SHALL keep result bytes on stdout or the selected output file and route progress, warnings, cache notices, repeatable `-v` and `-vv` diagnostics, and actionable failure hints outside machine-readable stdout.

#### Scenario: Machine output includes diagnostics

- **WHEN** a user requests JSON or JSONL while enabling verbosity or encountering non-fatal notices
- **THEN** stdout remains a complete parseable machine document or stream
- **AND** diagnostics are suppressed by quiet mode or written to stderr according to the documented verbosity contract

#### Scenario: URL pull fails in the domain

- **WHEN** resolution or retrieval is unsupported, ambiguous, missing, incomplete, non-authoritative, budget-exhausted, or rejected by transport safety
- **THEN** OpenOpps exits nonzero using the stable documented domain-error mapping
- **AND** emits an actionable hint without representing partial results as a successful pull

### Requirement: Existing CLI meanings remain stable

Adding URL-first retrieval SHALL NOT change the meanings of `jobs sync`, `jobs list`, `jobs show`, `jobs history`, `jobs export`, or existing advanced provider commands.

#### Scenario: User runs an existing jobs command

- **WHEN** the user invokes an existing jobs command without the new URL-pull surface
- **THEN** its command path, filtering model, persistence semantics, and output contract remain governed by the existing requirements

#### Scenario: User opens public help

- **WHEN** the user opens root, jobs, or providers help
- **THEN** semantic help documents URL inputs, operation selection, discovery controls, persistence defaults, cache independence, output formats, capability caveats, and failure behavior
- **AND** help remains covered by semantic assertions rather than brittle full-terminal snapshots
