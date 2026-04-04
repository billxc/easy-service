# Market Scan

## Similar Projects

### `service-manager-rs`

Good backend coverage and a solid abstraction layer, but the product center is broader than this repo's goal. `easy-service` wants a more opinionated no-admin UX.

### `serviceman`

A useful example of cross-platform service management, but the product surface is larger and the positioning is less tightly centered on current-user services.

### `WinSW`

A strong Windows-specific building block. It is not a cross-platform product and it trends toward classic service semantics instead of user-level simplicity.

### `daemonocle`

A clean Unix-focused daemon helper, but it does not solve the three-platform problem.

## Observed Gap

The gap is not "service management exists." The gap is:

- one tiny CLI
- user-scope by default
- no admin in the common path
- native platform artifacts
- straightforward mental model

That is the space `easy-service` is targeting.

