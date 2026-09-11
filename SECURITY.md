# Security

Context Guardian does not collect telemetry and does not persist conversation content.
The Pi adapter starts a local Python subprocess and communicates through stdin/stdout.
Provider credentials remain in Pi and are not sent to that subprocess.

The optional model provider receives the messages selected for inspection. Review
provider configuration and organizational data-handling requirements before enabling
external model calls.

Pi extensions execute with the permissions of the Pi process. Install packages only
from sources you trust.

Report security issues privately to the repository maintainers rather than opening a
public issue with secrets or exploit details.
