# FolioFrame Work Plan and Recovery Checklist

This document is the durable status sheet for the mockups, service hardening,
firmware distribution, CI/CD, repository refactoring, and cleanup. Update the
checkboxes and notes as work is completed so another session can resume
without relying on chat history.

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
- Refactor and clean the repository, not only the mockup files: remove
  confirmed dead code/configuration, archive obsolete planning/review
  documents with their references intact, and keep changes covered by tests.
- After implementation, review the complete change set deeply, run the
  appropriate tests, and create separate pull requests for logically
  independent change groups. Do not claim a PR exists until GitHub confirms it.

## Current session state

- Working tree: branch `post-merge-oauth-guidance`, based on the merged PR
  head; `origin/main` contains PR #1 at merge commit `379ca04`.
- PR #1 was merged into `main` on 2026-10-08; its merge commit is
  `379ca04c922f726c856a056289c83dfa37a71022`.
- The merged server-test job, Docker image build/push, and firmware build/
  release all succeeded. The Portainer redeploy job stopped before contacting
  Portainer because repository secret `CF_BYPASS_HEADER` was empty. The user
  will manage this deployment configuration.
- Since merge, the local worktree has uncommitted OAuth setup guidance,
  archive moves, dead image-pipeline cleanup, Firebase removal, and durable
  Google Photos import recovery; these are not part of PR #1.
- Exactly two top-level mockup files are present. The eight former standalone
  service mockups are no longer present; only the device mockup was tracked.
- On the merged commit, server tests and the Docker image build/push passed;
  firmware build and release 0.0.12/build 30 also passed. Portainer deployment
  remains user-managed because `CF_BYPASS_HEADER` is unset in repository
  Actions secrets.
- `build/` and `.pio/` contain generated artifacts; leave them ignored and do
  not stage them.
- Superseded root plans and review reports are now under `docs/archive/`,
  with cross-references updated. A broader route extraction remains deferred;
  the Google Photos worker is extracted and the remaining audit items are
  tracked below.
- Latest validation: server suite 140/140, firmware native suite 7/7,
  PlatformIO `ee02` build, Python compilation, and `git diff --check` passed.
  Earlier validation also covered firmware artifacts, workflow YAML, Compose
  configuration, and mockup screen order/embedded JavaScript. Release
  artifacts are packaged as firmware 0.0.12/build 30.
  `tools/stub_compile.sh` previously failed because its existing Arduino
  stubs omit APIs/types used by current sources; the real PlatformIO build
  passes.

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
- [x] Track the Google Photos picker as a persisted local job with an
      expiring worker lease, restart recovery, and durable status.
- [x] Improve missing OAuth setup guidance on the public welcome page: it now
      tells the administrator to configure `google.client_id` and
      `google.client_secret` in `SPECTRA_CONFIG_JSON`.
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
- [x] Move superseded root planning and review reports into categorized
      `docs/archive/` folders; update every repository and source-code
      reference and label the material historical.
- [x] Remove confirmed-dead tone/DRC/Bayer pipeline code, its no-op
      configuration field and imports; retain and test the active library
      pipeline.
- [x] Audit app/source/test/tool files for confirmed unreachable or obsolete
      code; remove only when references and behavior are covered by tests.
- [x] Audit vendored, generated, firmware-history, and runtime files; retain
      anything needed by flashing, OTA, deployment, builds, or user data.
- [x] Re-run repository searches and tests after file/code cleanup; confirm no
      broken references to moved plans/reviews, missing firmware assets, or
      ignored runtime data staged.
- [x] Update direct references and contributor documentation for the
      consolidated mockup filenames and release-driven firmware distribution.
- [x] Keep the requested durable recovery checklist in this file; it is not
      part of the runtime application or image.

### F. Final verification and review

- [x] Run the complete server suite (138 passed on the merged PR; 133 passed
      after obsolete pipeline tests were removed and current behavior retested).
- [x] Run firmware host-native tests (7 passed) and the actual
      `pio run -e ee02` build (passed).
- [x] Validate Python compilation, shell syntax, all workflow YAML files,
      compose configuration, mockup screen sequences/embedded JavaScript, and
      `git diff --check`.
- [x] Keep generated build/runtime artifacts out of the PR; release binaries
      in `server/firmware/` are intentional packaged deliverables.
- [x] Complete a deep review of the changed files; no significant issues
      remained after correcting release metadata and integrating the current
      `main` deployment changes.
- [x] Resolve PR #1's conflicts through `origin/main` `6737325`; revalidate
      workflows, deployment docs, firmware release artifacts, server
      compatibility, and tests.
- [x] Push the conflict-resolution commit to the PR branch and verify GitHub
      reports it mergeable with required checks passing.
- [x] Merge PR #1 into `main` through GitHub and record the merge commit:
      `379ca04c922f726c856a056289c83dfa37a71022`.

### G. Post-merge code cleanup and reliability work

- [x] Remove the inactive image-pipeline tone/DRC/Bayer implementation,
      unused imports and ineffective `tone` config field after confirming
      callers; keep the active `epaper-dithering` path and add regression
      coverage for its public contract.
- [x] Remove Firebase-specific storage and deployment integrations. Google
      sign-in and Google Photos remain supported via Google's OAuth APIs;
      test that JSON/filesystem state and blobs survive a local restart.
- [x] Assess further request/feature extraction from
      `server/spectra_server.py`. The Google Photos worker is separated;
      broader route extraction is deferred until a route change provides a
      concrete boundary, avoiding a mechanical compatibility-adapter rewrite.
- [x] Make Google Photos import jobs durable across process restarts using
      persisted job records and expiring worker leases in the existing local
      Store. Recovery retries the same Google media IDs safely; no queue
      service was added.
- [x] Reassess preview parity and per-device source selection as explicit
      product follow-ups; retain the current simulation/account-wide behavior
      and do not claim pixel-identical previews without validation.
- [x] Run the complete server and firmware suites and a final dead-code and
      reference audit after these improvements.

## Service audit notes

- Google Photos import jobs and OAuth tokens persist in the JSON registry;
  interrupted imports resume when their leases expire. Run one service
  instance with persistent local storage (as documented in `SELFHOST.md`).
- The live service supports uploaded and Google Photos content, but the
  mockup's picker-local additions and the current console upload surface are
  not the same interaction.
- The source selector changes the account-wide source, not a per-frame source.
- Web Serial/USB flashing requires a compatible desktop browser and HTTPS.
- The service uses a compatibility adapter around existing handlers rather than
  a complete route-by-route FastAPI rewrite.
- Google Photos network responses are capped at 25 MB; larger photo downloads
  fail rather than allowing an unbounded response to exhaust server memory.
- The browser e-paper preview is explicitly a simulation and is not pixel
  identical to the server `epaper-dithering` pipeline.
- OAuth/client setup guidance is improved in the local post-merge change; the
  generic provider-error handling remains intentionally non-specific.
- The container health check is a liveness check. It intentionally does not
  block service startup on GitHub firmware availability.

## Decision log

| Decision | Rationale |
|---|---|
| Keep two consolidated mockup files: one for device screens and one for service UI/UX. | User requirement. |
| Adopt FastAPI/Uvicorn while preserving the existing HTTP contracts. | User-selected framework approach. |
| Implement independent firmware releases and server deployment. | User-approved; retain the existing main-branch Docker Hub image and Git-managed Portainer redeploy choices when integrating newer base commits. |
| Persist photo-import jobs in the local Store with expiring worker leases. | User-selected reliability improvement without introducing another service; retries overwrite by stable Google media ID. |
| Keep JSON/filesystem storage as the only application-state backend. | The service must be deployable on any suitable host without a managed cloud storage dependency. |

## PR tracking

| Group | Branch | PR | Status |
|---|---|---|---|
| Consolidated mockups, server hardening, firmware refresh/CI | align-firmware-ui-with-mockups | [#1](https://github.com/CJ8664/folioframe/pull/1) | Merged to `main` as `379ca04` |
| Post-merge OAuth guidance, refactor, and cleanup | post-merge-oauth-guidance | Not opened | In progress; plan now tracks the remaining repository cleanup and reliability work |
