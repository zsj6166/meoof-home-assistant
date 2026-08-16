# Local runtime release audit

Audit date: 2026-08-16

The shipped runtime is built from `native/open_tutk_probe/` with Go 1.24. It
uses the vendored MIT-licensed go2rtc transport and Pion dependencies. The
release tree contains no QEMU executable, Android userspace, vendor SDK shared
library, vendor SDK authorization value, Android APK, device credential or
captured packet file.

## Verified device capabilities

The pure-Go runtime was exercised against the supported feeder for:

- UID/account/password authentication and local address discovery;
- status reads, event subscription and clean session shutdown;
- live H.264 video frames;
- recording index and cover download;
- multi-megabyte MP4 download over RDT with selective acknowledgements;
- fragmented TUTK/29 IOCTRL transmission and response reassembly;
- feed-plan reads and a same-value write/readback check.

The cover and MP4 results were compared byte-for-byte with previously known
files. The feed-plan verification wrote the exact bytes read from the device,
then confirmed that the returned plan was unchanged. No development or
automated test dispensed food.

## Release builds

Release binaries are statically built with `CGO_ENABLED=0`, `-trimpath` and
`-ldflags="-s -w"` for Linux amd64, arm64 and armv7. Their complete source,
module lock data, vendor source and upstream license files are part of this
repository. Checksums must be regenerated from the release artifact and
published with each release.

## Public history requirement

Earlier private development commits contained a compatibility bundle. Those
objects must never be pushed. The public repository must start from a clean
snapshot of the reviewed release tree, followed by a scan of every reachable
Git object and of the generated ZIP archive.
