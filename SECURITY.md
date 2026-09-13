# Security Policy

Do not report vulnerabilities through a public issue. Use GitHub's private vulnerability reporting
for this repository, or contact the maintainers through the private channel published by the owning
organization.

Governed Agent SDLC treats model output as untrusted. Hooks and CI must fail closed for credential access,
protected branches, artifact state, and destructive actions. Never run a privileged agent workflow
with repository secrets on an untrusted pull request.

Supported security fixes target the latest minor release until a formal support matrix is published.
