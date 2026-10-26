# VPN Shop v15 — Production Launch

## Required before release
- Provision Android/iOS/desktop signing and OS VPN entitlements.
- Attach a production WireGuard/native tunnel engine; the Android service and iOS Packet Tunnel Provider are integration points and intentionally do not inspect private payloads.
- Configure production payment provider, OIDC/SAML/SCIM credentials, APNs/FCM and secrets manager.
- Enable PostgreSQL/Redis HA, encrypted backups and restore drills.
- Run external penetration test and dependency/container scans.
- Configure OpenTelemetry collector, SLO alerts and canary rollback thresholds.
- Run device-farm tests across supported OS versions and Wi-Fi/cellular transitions.

## Privacy invariant
Corgi control-plane diagnostics MUST NOT inspect or persist private VPN payloads. Diagnostics are opt-in; telemetry is minimized and configurable.
