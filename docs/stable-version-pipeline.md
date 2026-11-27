# Jenkins stable-version discovery

The pipeline in `Jenkinsfile.stable-versions` uses self-hosted Renovate to
discover dependency updates and open pull requests in their owning GitHub
repositories. It does not install or validate updates and does not access a
deployment cluster. It runs weekly during the 02:00 UTC hour on Monday, within
Renovate's weekly update window. By default it runs discovery only. The optional
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
The self-hosted configuration groups Langfuse web and worker image updates and
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

Both stages fail if Renovate logs warnings or errors, or if its report does not
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

Pull requests require human review and a separate compatibility, deployment,
and validation workflow. Renovate is configured not to automerge; this pipeline
does not provide test, compatibility, backup, or rollback gates. In particular,
Istio's four chart dependencies must match and their chart lock and appVersion
need review. KServe and platform Envoy Gateway versions are cross-repository
dependencies and must be coordinated manually. Do not treat grouped proposals
as proof of compatibility or artifact availability.
