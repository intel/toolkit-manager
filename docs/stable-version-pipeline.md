# Jenkins stable-version discovery

The pipeline in `Jenkinsfile.stable-versions` uses self-hosted Renovate to
discover dependency updates and open pull requests in their owning GitHub
repositories. It builds an evidence-based upgrade matrix and runs offline static
checks, but does not install updates or access a deployment cluster.
It runs weekly during the 02:00 UTC hour on Monday, within
Renovate's weekly update window. By default it runs discovery and static checks only. The optional
PR-creation path is restricted to the approved Agent Sandbox pilot.

Renovate's GitHub vulnerability-alert integration is disabled for all
repositories in this job because its discovery credential cannot read the
Agent Toolkit Dependabot alerts. This does not change GitHub's repository
settings, but Renovate will not use those alerts to identify or prioritize
security updates. A separate approved vulnerability scan is needed; this
pipeline does not currently provide one.

## What it covers

Renovate reads the default branch of each configured repository. It inspects
recognized Helm charts, Helm values, Dockerfiles, Docker Compose files, and pip
requirements and GitHub Actions. Custom rules cover Agent Sandbox, KubeRay
operator, the vendored Redis Stack server image tag, vLLM CPU and OpenVINO Model
Server image variables, and the yq installer utility. Additional rules for
CloudNativePG, MetalLB, KEDA, Metrics Server, SeaweedFS, Langfuse,
and Node Feature Discovery apply only where those role paths exist; these
inherited roles are not present in the current Agent Toolkit repository.
Some rules may not match if the monitored branch
uses a different file layout or variable name. Matching files in a repository can
include disabled components and dependencies unrelated to the deployed stack.
The discovery report is not an inventory of what is actually running.

The self-hosted configuration now discovers both KubeRay operator version
references without requiring the unmerged
[PR #41](https://github.com/intel/agent-toolkit/pull/41). If that PR merges,
review duplicate custom rules in the effective Renovate config.
The self-hosted configuration groups Langfuse web and worker image updates,
groups OpenVINO Model Server image variants, and
disables Ray image updates until the image and chart application versions can
be updated consistently. Verify these safeguards in the discovery report before
enabling PR creation; they do not prove compatibility.

Renovate ignores versions it recognizes as unstable or prerelease. A proposed
version is an upstream candidate, not an Intel-certified compatibility claim.
Image tag conventions differ and some floating tags do not identify an
immutable release. The pipeline does not update firmware, OS packages,
Kubernetes installations, models, external services, or versions hidden in
unrecognized templates and runtime environment overrides. For complete
coverage, compare the discovery report to your deployment inventory and add
verified managers or rules for each missing component.

### Explicit repository component report

Before Renovate runs, `ci/discover-toolkit-releases.cjs` uses the read-only
discovery credential to resolve Agent Toolkit's `main` commit and inspect
the exact references declared in `ci/toolkit-components.json`. It queries
upstream GitHub releases for these 13 runtime products:

- Agent Sandbox
- KubeRay operator
- Ray
- OpenShell
- pgvector
- Redis Stack
- LiteLLM
- Flowise
- ClickHouse
- MinIO
- Langfuse (web and worker)
- vLLM (CPU image reference)
- OpenVINO Model Server (plain and Python image references)

The yq installer utility is reported separately as a fourteenth entry.
`stable-components.json` includes the source commit, observation timestamp,
current references, latest upstream stable release, source URL, status and
component-specific limitations. `stable-components.tsv` is the readable table.
GitHub's designated latest published non-prerelease is used for release-based
sources; this is not necessarily the numerically highest version of every
maintained release line. pgvector has no GitHub releases, so its explicit source
is all paginated tags and its highest stable `vMAJOR.MINOR.PATCH` tag.

The pgvector `pg16` image tag and `pgvector_version: "16"` identify the
PostgreSQL major, not the extension version. The report does not pretend the
installed extension version is known. Similarly, a source release is not proof
that a Bitnami legacy, LiteLLM stable-channel, CPU, Python or Helm artifact
exists. Consult Renovate's separate registry candidate report for those checks.
Ray and OpenShell are informational detections, not authorization for standalone
updates. OpenShell chart/image/CLI compatibility and registry migration require
review.

Missing expected references, failed upstream lookups (including HTTP 403/rate
limits), and invalid/draft/prerelease responses fail the component stage. Per-
component failures are written into the archived reports rather than skipped.
A failure to resolve the source commit is fatal before a component report can
be produced. Partial reports are never a successful coverage gate. This is a
curated inventory: additions to the toolkit require a reviewed manifest entry;
it does not automatically classify new components.

Keycloak deployment, Istio, inherited inference/platform services, and versions
in other repositories or existing environment overrides remain outside this
repository-only scope. This report does not claim whole-platform coverage.

Agent-toolkit and inference files under `ext/` and environment files under
`env/` are ignored by this checkout. Pull requests against the source
repositories do not update those existing local copies or already deployed
environments.

## Upgrade matrix and static gate

`ci/make-upgrade-matrix.cjs` joins the component report with the final Renovate
report using file, dependency name and exact current value. It requires the
complete curated inventory, fails on missing extraction/current-reference
drift, and rejects proposals without extracted lookup evidence. It writes:

- `stable-upgrade-matrix.json`: source commit, current references, registry/
  release lookup candidates, proposed changes per Renovate branch, blockers,
  required validation, and separate validation states.
- `stable-upgrade-matrix.tsv`: a readable current-to-candidate table.

The `ci/toolkit-upgrade-policy.json` policy defines the expected coordinated
references and required component-specific validation. Branch alternatives are
preserved rather than silently selecting a major upgrade. Candidate sets must
cover all coordinated references with matching versions. Ray, OpenShell and
pgvector stay explicitly blocked. An empty candidate list is `no-candidate`,
not proof that an image is current or available. Every row remains
`prEligible: false`: the matrix never authorizes PR creation.

Build #30 illustrates why source and artifact evidence must stay separate:

| Component | Current reference | Lookup proposal | Disposition |
|---|---|---|---|
| Agent Sandbox | v1.0.10 | v1.0.12 | Both references; release artifact checks pending |
| KubeRay operator | 1.3.0 | 1.8.0 | Both references; exact Helm download/CRD tests pending |
| Flowise | 3.1.2 | 3.1.4 | Unvalidated image candidate |
| ClickHouse | legacy mirror 25.2.1 | legacy mirror 25.7.5 | Not upstream 26.9.40.9 |
| MinIO | legacy mirror 2024.12.18 | legacy mirror 2025.7.23 | Not inferred from upstream release name |
| Langfuse web/worker | 3.106.1 | 3.227.1 or 4.88.0 | Separate coordinated alternatives; migration tests pending |
| vLLM CPU | v0.28.0 | v0.34.0 | CPU image candidate; hardware/model tests pending |
| OpenVINO Model Server | 2025.4.1 / 2025.4.1-py | plain 2026.4.1 only | Blocked: no matching Python proposal |
| yq | v4.44.1 | v4.54.3 | Binary checksum/execution tests pending |
| Redis Stack | 7.4.0-v8 | None | No candidate; not an artifact-availability check |
| LiteLLM | v1.83.14-stable.patch.2 | None | Stable image channel not resolved by upstream v1.111.0 |
| Ray | 2.40.0-py312 | Disabled | Coordinated image/client/chart update required |
| OpenShell | 0.1.6 | Not managed | Chart registry/image/CLI mapping required |
| pgvector | PostgreSQL 16 / pg16 | Invalid-value skip | Extension version unknown; do not replace with 0.8.7 |

`ci/validate-toolkit-config.cjs` validates a clean checkout at the exact
component report commit and verifies every current reference against the
manifest. Jenkins fetches this public source into a temporary directory, never
modifying the pipeline checkout or an existing deployment. It runs:

- Bash syntax checks for the deployment and Compose generator scripts.
- YAML parsing of the referenced configuration/defaults/values/metadata files.
- Helm lint and offline template rendering for KubeRay, pgvector and Redis
  Stack, using explicitly synthetic non-production passwords.
- The same checks on disposable copies containing each complete candidate
  proposal, with exact-match version substitutions. Partial/blocked proposals
  are not patched or validated as if complete.

Results and tool versions are archived in `stable-static-validation.json`.
Checkout checks parse Git stdout separately from stderr, so container user
configuration warnings cannot masquerade as dirty files or a different commit.
Global Git ignore/attributes files are disabled for these checks; remaining
diagnostics are printed and recorded. Real Git failures or dirty files still
block validation.
The matrix records static status independently from artifact digest, security,
deployment, smoke and rollback validation. A failing baseline is a blocking
pre-existing issue, not automatically a version regression. Candidate results
list failing commands already failing at baseline separately from newly failing
commands; this classification does not prove identical root causes.

At source commit `b3a29592ff6cb0dbc3adce0de8b334964db38e27`, Helm 3.20.2
reports a baseline Redis lint error: the locally vendored `redis-stack-server`
chart is absent from the parent dependency metadata. Template rendering passes,
but the lint gate intentionally fails. No toolkit source fix or lint suppression
is included here. Review and fix that issue in the source repository before
treating static validation as passing.

The source fix is published as commit
`ea16d845a200f125be85b9630660472f7e52fa66` on the approved fork branch
[`fix/redis-vendored-chart-metadata`](https://github.com/nishi252003/enterprise-agent-toolkit/tree/fix/redis-vendored-chart-metadata).
It declares the exact vendored chart version with
`repository: file://charts/redis-stack-server`, never an upstream chart
repository. Redis manifests rendered before and after the change are
byte-identical. The full baseline and all nine complete Build #30 candidate
snapshots pass the static gate on that commit. These are local static results,
not new registry discovery, runtime tests or a successful Jenkins build.
Submit and merge the source fix into `intel/agent-toolkit` `main` before
rerunning the job expecting a passing baseline; pushing the fork branch alone
does not change the monitored source. The pipeline does not apply the fix
silently to its validation checkout or suppress the failure.

Static console output prints each failing baseline command with its diagnostic
output. Candidate summaries identify checks that also failed at baseline and
print diagnostics for newly failing commands. The complete results remain in
the archived JSON report.

These are static syntax/render checks, not full Ansible lint, generated Compose
semantic validation, Kubernetes server-schema validation, chart/image digest
verification, vulnerability scanning or compatibility certification. Passing
them cannot enable non-pilot PR creation or deployments. A baseline failure also
prevents the existing pilot PR stage from running.

## Dedicated disposable-cluster setup (deployment disabled)

No cluster credential is bound and no deployment/smoke stage is enabled.
The user selected a dedicated disposable cluster; a GitHub credential such as
`gh-sys-aibot` is not a substitute for its Kubernetes kubeconfig.

1. Have the cluster owner provide a kubeconfig for an explicitly disposable
   cluster, not a production/shared-cluster context. Sandbox and KubeRay can
   change cluster-scoped CRDs/RBAC; a namespace alone does not isolate those.
2. In Jenkins, open the appropriate folder's **Credentials**, choose **Add
   Credentials**, and select **Secret file**. Upload that kubeconfig, choose a
   descriptive ID (for example `agent-toolkit-disposable-kubeconfig`), and
   restrict access to this trusted job. Never place the kubeconfig in Git or chat.
3. Supply only the credential ID and approved context name to the pipeline
   maintainer. The expected API server/cluster identity, Kubernetes version,
   resource/storage capacity, registry egress, and approved small inference
   model must also be confirmed before execution.
4. Before adding write operations, implement a fail-closed context/server
   allowlist, connectivity/RBAC checks, explicit manual opt-in, serialized
   cluster use, unique namespaces/resource ownership, bounded timeouts and
   scoped cleanup. Do not bind a credential or deploy until these gates and the
   component-specific smoke assertions are implemented and reviewed.
5. Test baseline install, candidate upgrade, component smoke assertions,
   persistence/backup/restore and rollback on disposable data. Archive test
   results and exact image/chart digests; skipped tests must not count as passed.

The per-component smoke requirements are in `ci/toolkit-upgrade-policy.json`;
they are requirements, not implemented/passing runtime tests.

## Jenkins setup

1. Commit `Jenkinsfile.stable-versions` and `ci/renovate-config.json` to a
   trusted repository branch. Review this configuration before granting it
   credentials.
2. Provide a trusted Jenkins Kubernetes cloud with the `proxy` pod template.
   The job uses the existing agent container for checkout and report checks,
   and a `renovate/renovate:44.257.9` container for Renovate. It requires a
   shared, writable workspace, Bash and `jq` in the agent container, permission
   to pull both images, and access to GitHub and relevant package registries.
   The Renovate container uses UID and GID 1000 to match the observed Jenkins
   workspace owner; verify or adjust these IDs if the agent setup changes.
   The pod provisions Helm 3.20.2 and mikefarah/yq 4.53.2 from digest-pinned
   `alpine/helm` and `mikefarah/yq` init-container images into a pod-local
   `emptyDir`. Allow those two images in the Jenkins cluster's image policy.
   The init containers run as UID 0 only to copy their binaries into that
   volume, with all capabilities dropped and read-only image filesystems.
   The nonroot Renovate container mounts the tools read-only. No host runtime,
   host filesystem, or target-cluster configuration is changed. Git, Bash and
   Node remain supplied by the existing Renovate image.
   Preparation checks tool execution/major versions before discovery; missing
   or incompatible tools report their individual command errors rather than
   one generic message. Static validation also records tool diagnostics on
   preflight failure. `XDG_CONFIG_HOME` points to the container's temporary
   home instead of the image's inaccessible `/home/ubuntu` configuration.
   No Docker daemon is required. HTTPS requests use
   `http://proxy-dmz.intel.com:912` (set in both `HTTPS_PROXY` and `https_proxy`);
   ensure this proxy is reachable and approved for GitHub access. Configure
   `HTTP_PROXY`, `http_proxy`, `NO_PROXY`, and `no_proxy` on the agent as required.
   Configure trusted CA certificates for the agent and container if the proxy
   performs TLS inspection. Do not copy environment-specific proxy credentials
   into Git.
3. Configure the Jenkins **Secret text** credential `renovate-github-token`
   for discovery; its value is passed to Renovate as the GitHub token.
   PR creation uses the separate **Username with password**
   credential `validation-agent-github-pat`, whose password field is passed to
   Renovate as the GitHub token. The credential owners must authorize the job
   and the discovery token must have read access to repository contents and
   metadata. For PR creation the account must be authorized to create or use
   forks, push branches to those forks, and open pull requests against the parent
   repositories. Repository and organization
   policies can restrict these operations; use organization-approved
   credentials and confirm permissions before enabling PR creation.
   The configured Git author is the approved Nishi Shah GitHub no-reply
   identity; update it if the organization assigns a dedicated bot identity.
4. Create a Pipeline job using **Pipeline script from SCM** and select
   `Jenkinsfile.stable-versions` as the script path. Restrict who can configure
   or run the job and access its artifacts. Never expose the credential to
   untrusted pull request builds or untrusted repository configurations.
5. Run once manually with `CREATE_PRS=false` first. The default
   `REPOSITORIES` value is the canonical `intel/agent-toolkit`; change it only
   when intentionally running against another authorized repository. Values
   must use `owner/repo,owner/repo` format with no spaces so report keys match.
   Check the
   `stable-discovery.jsonl` artifact and reconcile its
   extracted dependencies with the intended component inventory.
   The `stable-inventory.tsv` artifact summarizes extracted versions, proposed
   updates and skip reasons. It lists only dependencies Renovate recognized,
   not all files, missing components, or deployed versions.
   Also require all 14 entries in `stable-components.tsv` to have status `ok`;
   inspect `stable-components.json` for source commit and compatibility notes.
   That upstream-source report is separate from the registry candidates and
   skipped dependencies in `stable-inventory.tsv`.
   To test the approved Agent Sandbox patch in dry-run mode only, set
   `PILOT_DRY_RUN=true`, leave `CREATE_PRS=false`, and use
   `REPOSITORIES=intel/agent-toolkit`. The pilot requires exactly one proposal
   changing both version references from v1.0.10 to v1.0.12. If upstream
   changes, the check intentionally fails and requires review. This run does
   not create a PR.
   To check the PR credential account and its existing
   `nishi252003/enterprise-agent-toolkit` fork without changing GitHub, run
   with `VERIFY_PR_CREDENTIAL=true` and `CREATE_PRS=false`. The check verifies
   the fork's parent and reported push access, not permission to create pull
   requests. The fork contains existing work; obtain approval for Renovate to
   update its default branch before PR creation. This check runs in the
   Renovate container and requires curl and Node.js there.
6. To test PR creation, explicitly set `CREATE_PRS=true` with the repository
   set to `intel/agent-toolkit`. The job repeats the scoped dry run and verifies
   the PR credential before running Renovate against the same pilot config.
   It creates or updates only the Agent Sandbox pilot proposal in the
   `renovate-agent-sandbox-pilot/` namespace. The job checks for the open PR,
   but the live run can make changes before a subsequent check fails. Inspect
   GitHub and the archived report after any failure. The fork mode can update
   the approved personal fork's default branch. The job does not merge PRs,
   prove compatibility, or verify the PR's checks.
7. Jenkins applies the in-file weekly trigger after the pipeline has run from
   the configured SCM branch. Scheduled builds use parameter defaults and run
   discovery only. Confirm the job is authorized to run this trusted branch and that
   Jenkins honors the explicit UTC schedule.

Renovate report gates fail if Renovate logs warnings or errors, or if its report does not
show extracted dependencies for every requested repository. The report check
also fails if it finds a proposed Ray image update for Agent Toolkit. Investigate
the archived log instead of treating an incomplete scan as a successful run.
If discovery unexpectedly reports that it cannot access vulnerability alerts, it also
requests the same GitHub endpoint and prints only its HTTP status and whether
GitHub reports SSO authorization is required. This diagnostic requires `curl`
in the Renovate container; it does not print the token or alert contents and
does not bypass the report check.

The PR stage performs its own lookup; releases or base branches can change
between the two stages, so a PR may differ from the discovery report. Renovate
can create some PRs before a later repository or registry fails. Inspect the
logs and existing PRs after a failed run. A successful process exit does not
guarantee that every expected component was recognized: inspect the report,
including skipped dependencies, and add explicit coverage checks
before relying on it as a complete inventory.

Pull requests require human review and additional artifact/security,
compatibility and deployment validation. Renovate is configured not to
automerge; this pipeline's static gate does not provide runtime compatibility,
backup, or rollback gates. In particular,
Istio's four chart dependencies must match and their chart lock and appVersion
need review. KServe and platform Envoy Gateway versions are cross-repository
dependencies and must be coordinated manually. Do not treat grouped proposals
as proof of compatibility or artifact availability.
