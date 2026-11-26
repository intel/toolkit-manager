# Jenkins stable-version discovery

The pipeline in `Jenkinsfile.stable-versions` uses self-hosted Renovate to
discover dependency updates and open pull requests in their owning GitHub
repositories. It does not install or validate updates and does not access a
deployment cluster. It runs weekly during the 02:00 UTC hour on Monday, within
Renovate's weekly update window. By default it runs discovery only; set
`CREATE_PRS=true` after reviewing the discovery results.

## What it covers

Renovate reads the default branch of each configured repository. It inspects
recognized Helm charts, Helm values, Dockerfiles, Docker Compose files, and pip
requirements. Custom rules cover Agent Sandbox, the vendored Redis Stack server
image tag, CloudNativePG, MetalLB, KEDA, Metrics Server, SeaweedFS, Langfuse,
and Node Feature Discovery. Some rules may not match if the monitored branch
uses a different file layout or variable name. Matching files in a repository can
include disabled components and dependencies unrelated to the deployed stack.
The discovery report is not an inventory of what is actually running.

Agent Toolkit-specific rules for KubeRay and its version references are defined
in the target repository's `renovate.json`. That file must be present on the
scanned default branch for the self-hosted run to apply those rules. Until
[PR #41](https://github.com/intel/agent-toolkit/pull/41) is merged, do not treat
the Jenkins discovery as covering those custom version fields.

Renovate ignores versions it recognizes as unstable or prerelease. A proposed
version is an upstream candidate, not an Intel-certified compatibility claim.
Image tag conventions differ and some floating tags do not identify an
immutable release. The pipeline does not update firmware, OS packages,
Kubernetes installations, models, external services, or versions hidden in
unrecognized templates and runtime environment overrides. For complete
coverage, compare the discovery report to your deployment inventory and add
verified managers or rules for each missing component.

Agent-toolkit and inference files under `ext/` and environment files under
`env/` are ignored by this checkout. Pull requests against the source
repositories do not update those existing local copies or already deployed
environments.

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
   No Docker daemon is required. HTTPS requests use
   `http://proxy-dmz.intel.com:912` (set in both `HTTPS_PROXY` and `https_proxy`);
   ensure this proxy is reachable and approved for GitHub access. Configure
   `HTTP_PROXY`, `http_proxy`, `NO_PROXY`, and `no_proxy` on the agent as required.
   Configure trusted CA certificates for the agent and container if the proxy
   performs TLS inspection. Do not copy environment-specific proxy credentials
   into Git.
3. Create a Jenkins **Secret text** credential with ID
   `renovate-github-token`. Use a dedicated GitHub bot with read access to
   repository contents and metadata. A read-only token is sufficient for an
   initial discovery-only run. For PR creation use a personal access token
   authorized to create or use forks, push branches to those forks, and open
   pull requests against the parent repositories. Repository and organization
   policies can restrict these operations; use organization-approved
   credentials and confirm permissions before enabling PR creation.
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
6. After reviewing coverage, run with `CREATE_PRS=true`. Renovate opens or
   updates pull requests against the parent repositories using Renovate's
   experimental fork mode. It can create missing forks and update a fork's default branch;
   use dedicated bot-owned forks rather than forks containing personal work.
   It does not merge PRs. Target repositories must permit the bot to create
   pull requests. The configured repository default branch is the base; arrange
   a repository-specific base branch policy if another branch is needed.
7. Jenkins applies the in-file weekly trigger after the pipeline has run from
   the configured SCM branch. Scheduled builds use parameter defaults and run
   discovery only until the PR-creation default is deliberately changed after
   approval. Confirm the job is authorized to run this trusted branch and that
   Jenkins honors the explicit UTC schedule.

Both stages fail if Renovate logs warnings or errors, or if its report does not
show extracted dependencies for every requested repository. Investigate the
archived log instead of treating an incomplete scan as a successful run.

The PR stage performs its own lookup; releases or base branches can change
between the two stages, so a PR may differ from the discovery report. Renovate
can create some PRs before a later repository or registry fails. Inspect the
logs and existing PRs after a failed run. A successful process exit does not
guarantee that every expected component was recognized: inspect the report,
including skipped dependencies, and add explicit coverage checks
before relying on it as a complete inventory.

Pull requests require human review and a separate compatibility, deployment,
and validation workflow. Renovate is configured not to automerge; this pipeline
does not provide test, compatibility, backup, or rollback gates. In particular,
Istio's four chart dependencies must match and their chart lock and appVersion
need review. KServe and platform Envoy Gateway versions are cross-repository
dependencies and must be coordinated manually. Do not treat grouped proposals
as proof of compatibility or artifact availability.
