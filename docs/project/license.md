# License

luplo is licensed under
[AGPL-3.0-or-later](https://www.gnu.org/licenses/agpl-3.0.html).

## What this means

The AGPL is a copyleft license. In short:

- **You can use luplo freely** — locally, in your own projects, inside
  your company.
- **If you modify luplo** and **distribute those modifications or
  expose a modified version over a network**, you must publish the
  modified source under the AGPL as well. The "over a network" clause
  is what distinguishes AGPL from GPL.
- **You can build tools on top of luplo** (via CLI, MCP, or HTTP)
  without the AGPL touching your own product — the AGPL applies to
  derivative works of luplo itself, not to clients of its interfaces.

The canonical license text is at the repo root
([LICENSE](https://github.com/luplo-io/luplo/blob/main/LICENSE)).

## Why AGPL

- luplo is a long-term-memory service. Forks that silently diverge from
  upstream would fragment the decision-record format, which hurts every
  downstream user.
- AGPL aligns the incentive: if you improve luplo and run it as a
  service, the improvements come back to the community.
- For single-user / in-team deployments (which is most of luplo's
  intended use), AGPL is indistinguishable from MIT in practice.

If the AGPL doesn't fit your case, open an issue on GitHub and we can
discuss a commercial license arrangement. There isn't a formal process
yet — ask.

## Contributor License Agreement

External contributions will require a CLA once the project has a
process in place. Until then, contributions are accepted under the
AGPL and the implicit understanding that they become part of the
AGPL-licensed codebase.

See {doc}`contributing` for the working agreement.

## Third-party notices

Runtime dependencies and their licenses are visible via:

```bash
uv pip list
uv pip show <package>
```

No third-party code is bundled in this repository outside of
`uv.lock`-tracked wheels.
