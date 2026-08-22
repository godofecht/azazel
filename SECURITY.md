# Security policy

Azazel executes build configuration and build-time tools, so security reports
that can cause unintended command execution, dependency substitution, cache
poisoning, path traversal, or artifact confusion are treated as security issues.

Please avoid publishing exploit details in a public issue. If GitHub shows
**Report a vulnerability** on this repository's Security tab, use that private
channel. If private vulnerability reporting is unavailable, open a minimal issue
stating that you have a security report and need a private contact channel; do
not include the exploit or sensitive details in that issue.

The production-supported surface is defined in `docs/PRODUCTION.md`. Experimental
features, including the shared artifact cache, are not suitable for release or
security-sensitive artifacts until explicitly promoted into that support
contract.

Security fixes should include a regression test where practical and should not
be disclosed as fixed until affected revisions and the remediation are clear.
