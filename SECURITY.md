# Security policy

## Supported versions

Only the latest release of dazel receives security fixes. The 0.0.x line is no longer maintained.

| Version | Supported |
|---|---|
| 1.x | Yes |
| 0.0.x | No |

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Report it privately through
[GitHub private vulnerability reporting](https://github.com/ArmisSecurity/dazel/security/advisories/new).

Please include:

- the dazel version (`dazel --dazel-version`), OS and Docker version;
- a description of the issue and its impact;
- steps or a minimal `.dazelrc` that reproduce it.

We will acknowledge the report within 5 business days and keep you informed until it is resolved. Once a
fix is released we publish an advisory and credit you, unless you prefer to stay anonymous.

## Scope

dazel executes `.dazelrc`, `~/.dazelrc` and `.dazelrc.local` as Python, and it starts containers with
the mounts, privileges and environment those files configure. Running dazel in a repository is
equivalent to running that repository's code. Reports that need a malicious rc file therefore are not
vulnerabilities, unless dazel reads configuration from a place the user would not expect.

In scope:

- dazel running commands through a shell or expanding values beyond the documented forms;
- dazel acting on containers, images or files it did not create, e.g. the cleanup commands deleting
  outside the paths they document;
- vulnerabilities in the published image or in the release pipeline.
