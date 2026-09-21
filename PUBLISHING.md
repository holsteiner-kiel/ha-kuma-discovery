# Container publishing

Home Assistant uses `image` plus the exact `config.yaml` version, for example
`ghcr.io/holsteiner-kiel/ha-kuma-discovery:2.2.0`. No `latest` tag is required or
published. Do not put `:v<version>`, `:latest` or `{arch}` in the app's image field.

## Workflow

`Container images` uses Home Assistant builder composite actions 2026.09.0.
The matrix selects native `ubuntu-24.04` (amd64) and `ubuntu-24.04-arm`
(aarch64/Linux arm64) runners. Both versioned architecture images must succeed
before the generic manifest is published. The builder supplies `BUILD_ARCH`
and `BUILD_VERSION`; the Dockerfile preserves the HA app labels. Images and
the manifest are signed with GitHub OIDC/Cosign. Only publishing jobs need
`packages: write` and `id-token: write`; no personal token is stored.

Pull requests build both architectures without pushing. App tests, Python
compilation, startup shell syntax and metadata validation run before building.
The separate existing `Validate` workflow remains unchanged.

## Initial rollout

The reviewed **2.0.0** images were published from `release/2.0.0` before the image
reference reached the default branch. The temporary branch/version bootstrap was
removed after verification. All three GHCR packages are public:

- `amd64-ha-kuma-discovery`
- `aarch64-ha-kuma-discovery`
- `ha-kuma-discovery`

The workflow successfully verified anonymous pulls, HA architecture/version
labels, application runtime imports and the generic multi-architecture manifest.
A public GitHub repository does not automatically make new GHCR packages public,
so repeat these checks whenever a new package is introduced.

## Later releases

1. Consolidate the approved changes, version in `config.yaml`, startup banner,
   README/DOCS and changelog in a release preparation branch. Run validation.
2. Publish the reviewed commit as GitHub release `v<version>` (or `<version>`).
   The workflow rejects a release tag that differs from the app version and
   publishes container tags **without** the optional leading `v`.
3. Check both architecture builds, manifest platforms and anonymous access.
   Coordinate release preparation so users are not offered a version before
   its image is ready. For an image already prepared on a release branch,
   publish the release from that exact commit before updating the default branch.
4. Verify installation/update on amd64 and aarch64 Home Assistant systems.

Manual workflow runs default to build-only. Explicit publishing is allowed
only on `main`; the version must be ready for release. Forks and PR events
never publish to the project registry.

Version tags are write-once in this workflow (`skip-existing` on each image
and the manifest). A rerun never overwrites published tags. Retry a partially
published release only at the **same source commit**. If source or dependencies
must change, use a new version; do not delete/reuse tags to republish it.

## Base strategy and limits

`ghcr.io/home-assistant/base:3.24` selects the currently supported Alpine 3.24
multi-architecture line, replacing unbounded `latest`. This retains Bashio,
S6 and the existing package installation/startup method. The base patch level
and Alpine package repository can still advance; this is a stable OS-line pin,
not a byte-for-byte reproducible image. Final app version tags remain immutable
under the workflow. Update the base line deliberately with build/runtime checks.

Sources checked for this change:

- [HA publishing guidance](https://developers.home-assistant.io/docs/apps/publishing/)
- [BuildKit migration](https://developers.home-assistant.io/blog/2026/04/02/builder-migration/)
- [Builder 2026.09.0](https://github.com/home-assistant/builder/releases/tag/2026.09.0)
- [Supported base image tags](https://github.com/home-assistant/docker-base#base-images)
