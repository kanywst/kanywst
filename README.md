# Hi, I'm kt

I work on identity, authorization, and cloud native security — mostly in Go, increasingly in Rust.

## What I maintain

- [omega](https://github.com/kanywst/omega) — SPIFFE-compatible workload identity and OpenID AuthZEN 1.0 authorization in a single Apache-2.0 binary: Cedar PDP, SPIFFE federation, tamper-evident audit log, Kubernetes operator
- [opa-authzen-plugin](https://github.com/kanywst/opa-authzen-plugin) — OPA extended with the OpenID AuthZEN 1.0 Authorization API
- [y509](https://github.com/kanywst/y509) — a TUI for reading X.509 certificate chains
- [wimsey](https://github.com/kanywst/wimsey) — a vendor-neutral WIMSE (workload identity in multi-system environments) reference implementation in Rust
- [awesome-authorization](https://github.com/kanywst/awesome-authorization) — authorization engines, standards, and learning resources

## Upstream

Most of my open source time goes into finding and fixing authentication, authorization, and cryptography bugs in other people's projects. A few:

- [lldap#1469](https://github.com/lldap/lldap/pull/1469) — refresh and password-reset tokens were generated with a non-cryptographic PRNG
- [php-casbin#174](https://github.com/php-casbin/php-casbin/pull/174) — transitive role links skipped their domain condition, granting access that should have been denied
- [sigstore-go#645](https://github.com/sigstore/sigstore-go/pull/645) — a certificate identity with neither SAN nor issuer criteria matched any certificate
- [spicedb#3184](https://github.com/authzed/spicedb/pull/3184) and [openfga#3181](https://github.com/openfga/openfga/pull/3181) — the `in_cidr` caveat missed IPv4-mapped IPv6 addresses
- [rekor#2861](https://github.com/sigstore/rekor/pull/2861) — inclusion proof root hashes were compared without constant time
- [spiffe/spiffe#417](https://github.com/spiffe/spiffe/pull/417) — added WIT-SVID to the supported `use` values in the specification itself

[Everything that got merged](https://github.com/search?q=is%3Apr+author%3Akanywst+is%3Amerged+-user%3Akanywst+-org%3A0-draft&type=pullrequests) · [what's open](https://github.com/search?q=is%3Apr+author%3Akanywst+is%3Aopen+-user%3Akanywst+-org%3A0-draft&type=pullrequests)

## Writing

Around 100 deep dives on OAuth, OIDC, SPIFFE, AuthZEN, and the RFCs underneath them, at [dev.to/kanywst](https://dev.to/kanywst). Longer-form work and the full project list live at [kanywst.github.io](https://kanywst.github.io/).

[0-draft](https://github.com/0-draft) is where I keep research and teaching material — build-it-the-hard-way guides for WebAuthn, xDS, and SigV4, plus MCP bridges for OPA and AuthZEN.

## Guestbook

Leave a trace. If you visited, say hi — it takes 10 seconds.

[Sign the guest book](https://github.com/kanywst/kanywst/issues/new?template=guestbook.yml&title=%F0%9F%93%AE+%5BGuest+Book%5D) — opens a GitHub Issue form, one field, added below automatically.

<!-- GUESTBOOK:START -->
<table align="center">
  <thead>
    <tr>
      <th>🕐</th>
      <th>👤</th>
      <th>💬</th>
    </tr>
  </thead>
  <tbody>
    <tr><td><code>2026-03-23</code></td><td><a href="https://github.com/kanywst">@kanywst</a></td><td><a href="https://github.com/kanywst/kanywst/issues/2">‼️</a></td></tr>
  </tbody>
</table>
<!-- GUESTBOOK:END -->
