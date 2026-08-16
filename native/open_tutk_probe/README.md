# Open Meoof TUTK runtime

This Go runtime replaces the proprietary Android/QEMU transport for Meoof
feeders on the local network. Home Assistant uses it for device status, live
events, camera video, record indexes, recording downloads and feed-plan reads
and writes. It discovers the
feeder on the local `/24` and reports the resolved address for caching.

Credentials are accepted exclusively through `MEOOF_UID`, `MEOOF_ACCOUNT` and
`MEOOF_PASSWORD`; the command never prints them.

The transport implementation is imported from
[`github.com/AlexxIT/go2rtc/pkg/tutk`](https://github.com/AlexxIT/go2rtc/tree/master/pkg/tutk),
which is distributed under the MIT License. The dependency is pinned in
`go.mod`; its license and dependency metadata must be included in any release
that incorporates this prototype.

The vendored transport includes feeder-specific interoperability fixes:

- reassembly and transmission of fragmented TUTK/29 IOCTRL messages;
- RDT channel transport, selective acknowledgements and recording downloads;
- the session-close frame observed from the reference client, preventing
  abandoned sessions from exhausting the feeder's connection slots.

Manual feeding is implemented but is intentionally excluded from automated and
development tests. Feed-plan write tests only write the exact value that was
read and verify the same value afterwards, so they neither dispense food nor
alter the configured schedule.

```text
meoof-open-runtime                 # status
meoof-open-runtime events
meoof-open-runtime stream PATH
meoof-open-runtime records
meoof-open-runtime feed-plan
meoof-open-runtime download SOURCE DESTINATION
```

Optional discovery controls are `MEOOF_HOST`, `MEOOF_SUBNET` and
`MEOOF_CANDIDATES`. Authentication remains mandatory through `MEOOF_UID`,
`MEOOF_ACCOUNT` and `MEOOF_PASSWORD`; replacing the licensed transport does not
bypass device authentication.
