import logging

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration


def diagnostic_event(event, hint):
    # Rebuild instead of redacting: unknown fields and attachments may contain user code or credentials.
    hint.pop("attachments", None)
    safe = {key: event[key] for key in ("event_id", "timestamp", "level", "logger", "platform") if key in event}
    safe["logentry"] = {"message": "Application error"}
    exceptions = event.get("exception", {}).get("values", [])
    if exceptions:
        safe["exception"] = {"values": [{"type": item.get("type", "Error")} for item in exceptions]}
    return safe


def init_sentry(dsn):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration(), LoggingIntegration(level=None, event_level=logging.ERROR)],
        default_integrations=False,
        auto_enabling_integrations=False,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        include_source_context=False,
        max_breadcrumbs=0,
        auto_session_tracking=False,
        send_client_reports=False,
        enable_logs=False,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        profile_session_sample_rate=0.0,
        before_send=diagnostic_event,
    )
