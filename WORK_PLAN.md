# FolioFrame Work Plan and Recovery Checklist

This document is the durable status sheet for the in-flight mockup,
service-hardening, firmware-distribution, CI/CD, and repository-cleanup work.
Update the checkboxes and notes as work is completed so another session can
resume without relying on chat history.

## Goals and constraints

- Keep exactly two consolidated mockup review files:
  - `folioframe-device-mockups.html` — device screens in fresh-setup order.
  - `folioframe-service-mockups.html` — service screens in user-workflow order.
- Preserve the existing device/server HTTP contracts during the FastAPI/Uvicorn
  migration.
- Keep firmware and server build/deploy pipelines independent.
- Preserve the firmware release tag format `folioframe-vX.Y.Z`, manual
  `FW_VERSION` / `FW_BUILD` bumps in `src/main.cpp`, the current public Docker
  Hub image, Portainer CE API-token deployment, and the named `firmware` Docker
  volume.
- Runtime firmware refresh must only consume releases from the configured
  FolioFrame GitHub repository and must not replace current firmware until the
  release assets and metadata have been validated.
- Organize the repository conservatively: preserve useful historical
  documents, avoid deleting generated or user-owned state, and ask before
  ambiguous or behavior-affecting moves/deletions.
- After implementation, review the complete change set deeply, run the
  appropriate tests, and create separate pull requests for logically
  independent change groups. Do not claim a PR exists until GitHub confirms it.

## Current session state

- Working tree: branch `align-firmware-ui-with-mockups`.
- Latest committed branch update: `8d75fa6` (`Update work tracker with pull
  request status`); implementation commit `6665aa6` is pushed to
  `origin/align-firmware-ui-with-mockups`.
- The PR exists as #1 and targets `main`. The branch tracks its remote.
  A merge of `e9afa72` is being resolved locally; `origin/main` has since
  advanced to `c303a42`. The PR is not merged.
- Exactly two top-level mockup files are present. The eight former standalone
  service mockups are no longer present; only the device mockup was tracked.
- The firmware refresh endpoint, startup refresh, and three workflows are
  committed and pushed. Their live GitHub Actions, release publishing, and
  Portainer deployment behavior have not yet been confirmed.
- GitHub CLI is unauthenticated (checked 2026-10-08). PR #1 was created by the
  user. Earlier checks reported success for GitGuardian and CodeQL, with no
  review comments or approvals; these checks predate the current local edits.
  Preserve the current Docker Hub image and Git-managed Portainer redeploy
  flow from `main`.
- `build/` and `.pio/` contain generated artifacts; leave them ignored and do
  not stage them.
- The root review/verification Markdown files are tracked historical reports;
  they have cross-references, so retain them rather than moving or deleting
  them without a separate reference migration.
- Latest validation: server suite 138/138, firmware native suite 7/7, and
  PlatformIO `ee02` build passed. Release artifacts are packaged as firmware
  0.0.12/build 30. `tools/stub_compile.sh` previously failed because its
  existing Arduino stubs omit APIs/types used by current sources; the real
  PlatformIO build passes.

## Work items

### A. Consolidated mockups

- [x] Build the device mockup page from the existing combined device screens.
- [x] Build the service mockup page embedding the eight service screens.
- [x] Use data-driven gallery/navigation markup and shared asset references.
- [x] Add mobile/desktop previews and responsive outer-gallery styling.
- [x] Correct the device ID samples to the server's `ff-` format.
- [x] Recheck screen order, embedded documents, and JavaScript syntax:
      5 device screens (setup → pairing → OTA → photo → alerts) and 8 service
      screens (welcome → sign-in → photos → picker → pairing → devices →
      settings → firmware).
- [x] Confirm exactly two top-level mockup files remain and the galleries
      retain responsive mobile/desktop previews.

### B. Service framework and operational hardening

- [x] Add FastAPI/Uvicorn while routing existing requests through the legacy
      handler adapter to preserve current endpoints and response behavior.
- [x] Bound request bodies and concurrency; add request IDs and structured
      request/error logs.
- [x] Add `/healthz` and manage the rotation worker with the application
      lifespan.
- [x] Add focused adapter tests and update Docker health check and self-hosting
      documentation.
- [x] Validate bounded request bodies, concurrency, request IDs, structured
      logs, legacy responses, lifecycle startup, and the health endpoint.
- [x] Configure/document exact trusted proxy peers for forwarded client IPs;
      Uvicorn proxy-header rewriting remains disabled.
- [x] Run the full server suite after the final adapter and updater changes:
      138 tests passed after the PR conflict resolution.
- [x] Record remaining service UX/feature gaps below without implying that
      the compatibility adapter or in-process photo import is fully
      production-grade.

### C. Firmware release refresh and independent CI/CD

- [x] Implement a bounded, public `POST /api/firmware/refresh` endpoint that
      checks GitHub Releases for stable `folioframe-vX.Y.Z` releases.
- [x] Validate release tags, required asset names, `VERSION`, uint32 `BUILD`,
      firmware minimum/maximum size and ESP app magic, HTTPS redirects, and any
      published SHA-256 digest before installation.
- [x] Download to a temporary directory, install atomically per file, retain
      older `firmware-X.Y.Z.bin` files, and publish `BUILD` last so OTA does not
      see a partially installed release.
- [x] Add request throttling, global refresh coalescing/cooldown, bounded
      network timeouts, and explicit logs/errors for the unauthenticated
      refresh route.
- [x] Start an automatic refresh in the application startup lifecycle without
      delaying health/readiness. Keep legacy `/flash` binaries and the
      `firmware` named volume intact.
- [x] Add a public `/flash` “Check for firmware updates” action with visible
      progress/result/error states; keep USB flashing clearly desktop-browser
      only.
- [x] Add hermetic tests for successful updates, cached no-op, malformed and
      out-of-range metadata, invalid digest/redirect/URL/image, failed
      downloads, and preservation of existing firmware on failure.
- [x] Add `.github/workflows/firmware.yml`: firmware-only main-branch trigger,
      PlatformIO build/package, and GitHub release using the
      `folioframe-vX.Y.Z` tag and specified firmware metadata/binary assets.
- [x] Add `.github/workflows/deploy.yml`: server-only path filters, published
      `latest` and `sha-<short>` Docker images, Portainer CE API-token redeploy,
      then an HTTPS health poll with a five-minute ceiling.
- [x] Add `.github/workflows/pr-build.yml`: PR-only firmware compile gate;
      no release or deployment.
- [x] Ensure deploy path filters include server requirements, the test runner,
      and the deployment workflow, but exclude `server/firmware/**`.
- [x] Update firmware publishing/deployment documentation and compose comments
      to describe release-driven runtime refresh rather than manual file copy.
- [x] Confirm the `firmware` named volume persists and is never removed or
      reinitialized by the workflow.

### D. Service UX and feature audit

- [x] Verify the mockup-to-live-service flow mapping: welcome/sign-in, Photos
      connect/picker, frame pairing, device management/settings, and firmware
      flashing.
- [x] Document verified differences: device settings are inline in the
      console; source selection is account-wide; the picker’s local uploads
      are available through the console upload flow; Google sign-in’s account
      chooser is provider-managed; Web Serial flashing is desktop-only.
- [x] Track the Google Photos picker as an in-process daemon task with
      process-local status. A durable job queue/state store is a separate
      infrastructure decision; do not claim crash-safe imports without it.
- [x] Record missing OAuth setup/preflight guidance as follow-up; the welcome
      page currently gives a generic not-configured error rather than an
      operator-oriented setup action.
- [x] Compare the e-paper preview with the production pipeline. The live
      browser preview uses its own tone map and Lab/Floyd-Steinberg
      approximation; the server uses `epaper-dithering` tone/gamut mapping.
      The UI labels it a simulation, but pixel-accurate preview remains a
      follow-up.

### E. Repository structure audit

- [x] Inventory tracked mockup files and likely generated/vendor/runtime
      artifacts; distinguish the intentional firmware/web-flasher assets and
      runtime state from obsolete mockup sources.
- [x] Search references before considering root planning/review documents,
      source mockups, or other candidates for moves/deletion.
- [x] Make only clearly safe organizational changes. Preserve historical
      review evidence with cross-references; keep `.pio/`, `build/`, runtime
      server data, and vendor assets untouched.
- [x] Update direct references and contributor documentation for the
      consolidated mockup filenames and release-driven firmware distribution.
- [x] Keep the requested durable recovery checklist in this file; it is not
      part of the runtime application or image.

### F. Final verification and review

- [x] Run the complete server suite (138 passed) and focused firmware-refresh
      and FastAPI adapter tests (13 passed).
- [x] Run firmware host-native tests (7 passed) and the actual
      `pio run -e ee02` build (passed).
- [x] Validate Python compilation, shell syntax, all workflow YAML files,
      compose configuration, mockup screen sequences/embedded JavaScript, and
      `git diff --check`.
- [x] Keep generated build/runtime artifacts out of the PR; release binaries
      in `server/firmware/` are intentional packaged deliverables.
- [ ] Complete the requested deep final code review of all changed files; fix
      findings and rerun affected tests. This is still outstanding.
- [ ] Finish deep review and resolve PR #1's conflicts with the latest `main`.
      Revalidate merged workflows, compose/deployment docs, firmware refresh,
      server compatibility, and tests.
- [ ] Push the conflict-resolution commit to the PR branch and verify GitHub
      reports it mergeable with required checks passing.
- [ ] Merge PR #1 into `main` using GitHub's PR merge mechanism (not a direct
      push to `main`), then confirm the merge commit and record its URL below.

## Service audit notes

- The Google Photos import worker currently stores status in per-process
  controller state. A restart or scale-down can stop an import and lose its
  status; durable task state/queueing is not part of the current implementation.
- The live service supports uploaded and Google Photos content, but the
  mockup's picker-local additions and the current console upload surface are
  not the same interaction.
- The source selector changes the account-wide source, not a per-frame source.
- Web Serial/USB flashing requires a compatible desktop browser and HTTPS.
- The service uses a compatibility adapter around existing handlers rather than
  a complete route-by-route FastAPI rewrite.
- The browser e-paper preview is explicitly a simulation and is not pixel
  identical to the server `epaper-dithering` pipeline.
- OAuth/client setup failures need clearer operator-facing diagnostics; the
  existing docs explain server setup, but the welcome-page error is generic.
- The container health check is a liveness check. It intentionally does not
  block service startup on GitHub firmware availability.

## Decision log

| Decision | Rationale |
|---|---|
| Keep two consolidated mockup files: one for device screens and one for service UI/UX. | User requirement. |
| Adopt FastAPI/Uvicorn while preserving the existing HTTP contracts. | User-selected framework approach. |
| Implement independent firmware releases and server deployment. | User-approved; retain the existing main-branch Docker Hub image and Git-managed Portainer redeploy choices when integrating newer base commits. |

## PR tracking

| Group | Branch | PR | Status |
|---|---|---|---|
| Consolidated mockups, server hardening, firmware refresh/CI | align-firmware-ui-with-mockups | [#1](https://github.com/CJ8664/folioframe/pull/1) | Open; conflicts with updated main; review and merge pending |
