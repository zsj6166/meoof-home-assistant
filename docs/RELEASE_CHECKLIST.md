# Public release checklist

## Source and licensing

- [x] Replace the QEMU/Android/vendor-SDK bundle with the source-built Go runtime.
- [x] Include upstream license files and third-party notices.
- [x] Build Linux amd64, arm64 and armv7 binaries from the checked-in source.
- [x] Create the public repository from the reviewed snapshot, not the private history.
- [x] Scan every public Git object and release archive for credentials and private data.

## GitHub and HACS metadata

- [x] Select the final GitHub owner and repository name.
- [x] Update `manifest.json` documentation, issue tracker and code owner.
- [x] Enable Issues and add `home-assistant`, `hacs`, `meoof`, `pet-feeder` topics.
- [x] Create a GitHub Release for the final tag.

## Validation

- [x] Python compilation and unit tests pass.
- [x] Go root and vendored transport tests pass.
- [x] Every JSON file parses and `meoof-card.js` passes `node --check`.
- [x] Hassfest and HACS validation pass.
- [ ] The exact release artifact installs into a clean HA instance.
- [ ] Setup, reauthentication, unload/reload and uninstall are verified.
- [x] Camera, event subscription, safe food-level test and playback download pass.
- [x] No automated or release test performs manual feeding.

## Artifact

- [x] Archive contains exactly one integration under `custom_components/`.
- [x] Archive contains no private screenshots, recordings, packet captures, HA storage or secrets.
- [x] Archive size and supported architectures match the README.
- [x] Runtime SHA-256 checksums are included in `RUNTIME_CHECKSUMS.txt`.
