# conformance/

Adapter correctness, tested the way `prajna-schemas` tests Smriti resolution: captured host payloads
in, expected normalised observations out, byte-for-byte.

```sh
./conformance/claudecode/check.sh
```

**Byte-for-byte, not "semantically equivalent".** The fields most likely to drift are the nulls and
their reason codes, and a looser comparison is exactly the one that stops noticing when a reason
quietly changes from `host_does_not_emit` to `not_applicable`.

## The fixtures that matter

| Fixture | Pins |
|---|---|
| `happy-path` | The ordinary session, and that an interactive `permission_mode` produces **no gate** |
| `gap-missing-posttooluse` | A requested tool call with no recorded outcome survives as a hole (`collection_failed`) instead of being dropped |
| `unattended-bypass` | `bypassPermissions` is a positive finding: `auto_approved`, null actor |
| `malformed-line` | A corrupt capture line is counted, not swallowed |

The gap and malformed cases are the point. A kit that only tests clean input tests the half that was
never going to be wrong.
