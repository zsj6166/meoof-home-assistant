# Contributing

Keep changes independent of personal entity IDs, IP addresses, phone numbers
and cat names. Never commit credentials, snapshots, recordings or exported Home
Assistant storage. Feeding tests require an explicit opt-in and must not be part
of automated tests.

Before submitting a change, compile the Python files, validate all JSON files,
check the JavaScript syntax, run the Go tests, and scan the staged diff for
private data. Changes to the local runtime must keep builds reproducible and
preserve all vendored dependency notices.
