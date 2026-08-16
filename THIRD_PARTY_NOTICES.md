# Third-party notices

The distributed device runtime is built entirely from the source under
`native/open_tutk_probe/`. It does not contain or load QEMU, Android userspace,
ThroughTek/TUTK SDK libraries, or a vendor SDK authorization key.

The Go source vendors these MIT-licensed dependencies so release builds are
reproducible without downloading code:

- `github.com/AlexxIT/go2rtc` v1.9.14 — Copyright (c) 2022 Alexey Khit
- `github.com/pion/randutil` v0.1.0 — Copyright (c) 2020 Pion
- `github.com/pion/rtp` v1.10.0 — The Pion community
- `github.com/pion/sdp/v3` v3.0.17 — Copyright (c) 2023 The Pion community

Their complete license texts are included next to their source in
`native/open_tutk_probe/vendor/`. The integration and generated runtime binaries
are distributed under the terms of those notices and this project's MIT
license. Protocol interoperability does not imply endorsement by ThroughTek,
TUTK, Kalay or Meoof.
