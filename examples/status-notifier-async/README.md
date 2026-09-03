# Status Notifier Async

Example project for parity corpus: receives a status notification event via HTTPS, enriches message headers and exchange properties, performs a Request-Reply status check, logs the notification event, and hands off to ProcessDirect.

## Topology
`sender-http` (HTTPS POST `/status_notifier_event`) -> `set-headers` (modifier.content) -> `rr-status-check` (receiver.http Request-Reply) -> `log-event` (log.message) -> `pd-terminator` (receiver.processdirect `/status_notifier_pd`)
