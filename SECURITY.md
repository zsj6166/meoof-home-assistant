# Security and privacy

Report vulnerabilities privately through GitHub's Security Advisories for
`zsj6166/meoof-home-assistant`. Do not attach account credentials, SMS codes,
device passwords, snapshots or recordings to a public issue.

Credentials are stored in Home Assistant's configuration directory in
`meoof-device-secrets.json`. Cat reference images and event snapshots are kept
under `.meoof-cats/`. Neither location belongs in source control; both are
excluded by this repository's `.gitignore`.

If external image recognition is enabled, selected feeder snapshots and the
configured prompt are sent to the API endpoint chosen by the user. The project
does not enable this feature by default.

The currently observed Meoof-compatible cloud endpoint uses HTTP. Its HTTPS
endpoint does not pass hostname verification. Phone numbers, SMS verification
codes and cloud-query parameters therefore do not have reliable transport-layer
protection. This is an upstream compatibility limitation and must be accepted
before using account login or cloud history.

The released local runtime is the source-built Go implementation under
`native/open_tutk_probe/`; it contains no vendor SDK library or embedded SDK
authorization value. Release maintainers must still scan the complete public
Git object database and release archive before every publication.
