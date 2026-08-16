# Changelog

## 1.0.0-rc.1

- Replace the Android/QEMU/vendor-SDK compatibility bundle with a source-built,
  pure-Go local runtime for status, events, live video, recording indexes,
  RDT recording downloads and guarded feed-plan updates.
- Add Linux amd64, arm64 and armv7 runtime builds.
- Add fragmented TUTK/29 command transmission, RDT selective acknowledgements,
  correct command ACK sequencing and graceful session shutdown.
- Verify same-value feed-plan writes with readback and validate recording
  downloads against known files without dispensing food.
- Remove all vendor SDK libraries, Android userspace and QEMU from the release.

## 0.9.2

- Store smart-feed snapshots outside `/config/www` and serve them through
  signed URLs.
- Migrate legacy smart-feed snapshots from the public `/local/` directory.
- Add English config-flow translations, release validation workflows, issue
  templates, public-release checklist and reviewed README screenshots.

## 0.9.1

- Add a reusable smart-feed dashboard card with current food level, snapshot,
  confidence, safe test action and a relative food-level trend.
- Load smart-feed audit history immediately after integration startup.

## 0.9.0

- Add guarded read/modify/write support for disabling one item in today's feed
  plan and verifying the full plan after the change.
- Add fail-open visual checks before scheduled feeding, persistent audit records,
  Home Assistant notifications and the `meoof_feed_suppressed` event.
- Add the read-only “test food level” button; it never feeds or changes a plan.

## 0.8.1

- Backfill 30 days of Petkit T3/T4 litter events and rescan recent days hourly.
- Split Meoof cloud history into two-day windows to bypass the server's 30-record response cap.
- Backfill seven days of foraging events without launching hundreds of old recognition jobs.
- Merge incremental cloud results by event ID so records remain available after they leave the upstream window.

## 0.8.0

- Bundle and automatically register the Lovelace cards.
- Auto-discover integration entities for single-feeder installations.
- Add reusable today-eating, feed-timeline, latest-eating and event-management cards.
- Add local cat profiles, image review/reclassification and optional external vision recognition.
- Fix deletion of cat profiles from the options flow.
