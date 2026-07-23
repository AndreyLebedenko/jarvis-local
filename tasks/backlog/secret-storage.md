# Backlog note: storing secrets outside plain-text config

**Status:** Under review. Direction agreed, scope and proportionality not
yet settled; not a v1.6.2 task card - v1.6.2 accepted plain text
deliberately and documented it.
**Raised by:** the owner, 2026-07-23, reviewing task v1.6.2-6; the two
directions below are the owner's own framing.
**Scope:** every sensitive config value, not the camera alone. The LAN
camera password is simply the first one.

## What this is about

A LAN camera's password sits in `config.toml` in clear text. Task 6
removed the URL-assembly class of failures around that password, but not
the storage question: anything that can read the file has the camera.

The threat is not the network - RTSP never leaves the LAN, and the
two-tier locality contract already governs that axis. The threat is read
access to the file, and the list of readers is longer than it looks: a
backup or sync client, an editor's crash-recovery copy, a screen share of
an open config, a paste into a bug report, and - the reason this matters
in this project specifically - a coding agent with filesystem access
working in the repository. `config.toml` is gitignored, which stops the
worst outcome, not the common ones. Exposure is also not limited to the
camera: a password reused from elsewhere is a password for everything
else it was reused on, which is the realistic case for a consumer device
set up in a hurry.

The next secret is already visible - an MCP server token is the obvious
candidate - so whatever lands must be a project mechanism, not a camera
one. Two competing mechanisms would be worse than the current plain text.

## Proportionality (owner, 2026-07-23)

This is a single-user desktop assistant, not a hardened system, and the
design should stay sized to that:

- **The user's own choices bound what any mechanism can achieve.** Someone
  who keeps everything carelessly will also pick `12345`, and no storage
  design rescues that. The goal is to stop the ordinary accidents listed
  above - a copied file, a pasted config, an agent reading the repo - not
  to defend a secret against its own owner.
- **Not military grade.** No threat model with a motivated local attacker,
  no anti-forensics, no key ceremony. A mechanism that is correct,
  understandable in one sitting, and actually used beats a stronger one
  that makes the human give up and go back to plain text.

The two honest limits recorded below are not arguments for building more.
They are there so the card promises what it delivers: whatever ships,
`PROJECT.md` and the config documentation should state plainly what it
protects against and what it does not - the same standard the data-source
axis is already held to.

## Option 1: system keyring

The secret lives in Windows Credential Manager (via `keyring`); config
carries only a reference.

- Cheap to build, no cryptography to get wrong, nothing for the human to
  remember, and a pasted or backed-up config no longer leaks anything.
- Cost: a runtime dependency, a first-run enrolment step, and a config
  that is no longer self-contained - moving Jarvis to another machine
  means re-enrolling every secret.
- Honest limit, and the reason this is not automatically the answer: the
  Credential Manager is unlocked for the whole logged-in session, so any
  process running as the user can read the secret back through the same
  API. It defends against a file being copied, not against local code
  running as the user - including the coding agent named above.

## Option 2: master password with encrypted values in config

The owner's design, and the one with the better end state:

1. A `master-password-location` option, initially a filesystem path
   (later, other sources - the keyring above is a natural second one).
2. Symmetric text-to-text encryption for any sensitive option, marked by
   a prefix so encrypted and plain values coexist in one file and a
   migration is per-value rather than all-at-once.
3. The derived key is held in protected memory for the process lifetime.
4. Decryption on demand, at the point of use, not at config load.
5. A separate CLI utility that turns a typed secret into the encrypted
   value the human pastes into config.

Two things to describe accurately rather than assume - stated as limits to
document, not as gaps to close:

- **A master password read from a file is protection by location, not by
  cryptography.** Whoever can read that file can read every secret. It is
  still a real improvement - one file, outside the repo, outside backups,
  outside whatever the agent is pointed at - but the card should not
  claim more than that. Cryptographic protection only starts when the
  master secret comes from something that is not sitting on disk next to
  the data it protects: typed at startup, or held by the keyring in
  option 1. This is why the two options compose rather than compete, and
  why `master-password-location` being an option rather than a path is
  the right shape.
- **"Protected memory" is weak in Python and must not be overpromised.**
  Strings are immutable, the GC copies freely, and there is no portable
  `mlock`. Realistically achievable: keep the key in a `bytearray` that
  is zeroed after use, never place it in a dataclass that gets repr'd or
  logged, keep its lifetime as short as decryption-on-demand allows. Not
  achievable: a guarantee it never reaches swap or a crash dump. Say so
  in the design rather than implying a hardened enclave.

## Boundaries for whoever picks this up

- Keep the task-6 invariant intact: the secret is written literally by the
  human, encoded in exactly one place, and never reaches a log, an event
  payload, or an exception message. A decrypted value must not widen that
  surface - in particular, config error messages must never echo a
  decrypted value back.
- Solve it once for the project. The mechanism belongs next to config, not
  next to the camera.
- Migration must be non-breaking: an existing plain-text password keeps
  working, or fails with an error that says exactly what to do.
- The encryption format needs a version marker in the prefix from day one,
  so the algorithm can be changed later without guessing what old values
  are.
- The CLI utility is part of the deliverable, not a follow-up. Without it
  the human has no way to produce a value, and the feature is unusable in
  practice however correct the runtime half is.
