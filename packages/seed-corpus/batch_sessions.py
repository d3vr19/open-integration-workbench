"""Batch 2 + Batch 3 session definitions (WP-07 Track B-004 + B-005).

Batch 2 (B-004): 10 sessions targeting DIFFERENT archetypes to build
cross-task diversity:
  - 2 sessions: api-to-erp patterns
  - 2 sessions: file-to-api patterns
  - 2 sessions: paginated-api-ingestion patterns
  - 2 sessions: event-driven/webhook patterns
  - 2 sessions: error-handling patterns

Batch 3 (B-005): 10 sessions with MULTI-STEP corrections (the agent
fails in multiple ways, and the correction requires multiple actions):
  - 3 sessions: corrections requiring 3+ typed actions
  - 3 sessions: corrections requiring resource creation + flow patching
  - 2 sessions: corrections requiring edge rewiring
  - 2 sessions: corrections requiring configuration externalization

Each session follows the same dict schema as SESSIONS in run_learning_sessions.py:
  {
    "failure_mode": str (fm-XXX from failure-modes.yaml),
    "archetype": str,
    "requirement": str,
    "failed_steps": [(action_type, normalized, args, result_status, summary), ...],
    "correction_actions": [(action_type, normalized, args), ...],
  }
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Batch 2: Diverse archetypes (B-004)
# --------------------------------------------------------------------------- #

BATCH_2_SESSIONS = [
    # ---- 2 sessions: api-to-erp ----
    {
        "failure_mode": "fm-002",  # retry without idempotency
        "archetype": "api-to-erp",
        "requirement": "Post customer orders to S/4HANA with retry on transient HTTP 5xx failures.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "order-post", "", ""),
                {"flowId": "order-post", "name": "Order Post"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.http",
                                "config": {"path": "/orders", "methods": ["POST"]},
                            },
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://s4.example.com/api/orders",
                                    "method": "POST",
                                    "retry": {"maxAttempts": 5, "backoffMs": 2000},
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added retry receiver WITHOUT idempotency key",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W003: retry on POST without idempotency",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "receiver.http", "headers", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {
                                "headers": {"Idempotency-Key": "${header.MessageId}"}
                            },
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-010",  # hardcoded tenant URL
        "archetype": "api-to-erp",
        "requirement": "Build an order submission flow targeting the S/4HANA tenant.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "order-submit", "", ""),
                {"flowId": "order-submit", "name": "Order Submit"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://mytenant.s4.example.com/api/orders",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added receiver with HARDCODED tenant URL",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W005: hardcoded tenant URL",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "receiver.http", "url", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"url": "${TENANT_URL}/api/orders"},
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: file-to-api ----
    {
        "failure_mode": "fm-008",  # missing timeout
        "archetype": "file-to-api",
        "requirement": "Read CSV files from SFTP and post each row to a REST API.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "csv-to-api", "", ""),
                {"flowId": "csv-to-api", "name": "CSV to API"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.sftp", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.sftp",
                                "config": {
                                    "host": "sftp.example.com",
                                    "path": "/inbox",
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added SFTP sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://api.example.com/ingest",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },  # NO timeout
                "applied",
                "Added receiver WITHOUT timeout",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W001: missing timeoutSeconds",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.http",
                    "timeoutSeconds",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"timeoutSeconds": 30},
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-003",  # missing error subprocess
        "archetype": "file-to-api",
        "requirement": "Build an SFTP-to-HTTP file ingestion flow that handles malformed files gracefully.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "file-ingest", "", ""),
                {"flowId": "file-ingest", "name": "File Ingestion"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.sftp", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.sftp"},
                        }
                    ]
                },
                "applied",
                "Added SFTP sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "receiver", "type": "receiver.http"},
                        }
                    ]
                },
                "applied",
                "Added HTTP receiver",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W002: no errorHandling",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [
                                        {"id": "log-err", "type": "log.message"},
                                        {"id": "quarantine", "type": "receiver.sftp"},
                                    ]
                                }
                            },
                        }
                    ]
                },
                "applied",
                "Added exception subprocess",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: paginated-api-ingestion ----
    {
        "failure_mode": "fm-001",  # missing pagination bound
        "archetype": "paginated-api-ingestion",
        "requirement": "Fetch all products from the upstream OData service and forward each to the catalog API.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "product-fetch", "", ""),
                {"flowId": "product-fetch", "name": "Product Fetch"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.odata-v4", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.odata-v4",
                                "config": {
                                    "serviceUrl": "https://api.example.com/odata",
                                    "entitySet": "Products",
                                    "operation": "GET",
                                },
                            },
                        }
                    ]
                },  # MISSING pagination
                "applied",
                "Added OData receiver WITHOUT pagination",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-E003: unbounded pagination",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.odata-v4",
                    "pagination",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"pagination": {"maxPages": 50, "pageSize": 100}},
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-009",  # content-type mismatch after transform
        "archetype": "paginated-api-ingestion",
        "requirement": "Paginate over an OData API returning XML, transform each page to JSON, and post to a downstream service.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "paginate-transform", "", ""),
                {"flowId": "paginate-transform", "name": "Paginate + Transform"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.odata-v4", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "odata",
                                "type": "receiver.odata-v4",
                                "config": {
                                    "operation": "GET",
                                    "pagination": {"maxPages": 50},
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added OData receiver",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "transform.xml-to-json", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "transform",
                                "type": "transform.xml-to-json",
                            },
                        }
                    ]
                },
                "applied",
                "Added XML→JSON transform",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "downstream",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://downstream.example.com",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },  # NO Content-Type update
                "applied",
                "Added downstream WITHOUT Content-Type modifier",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "CONTENT_TYPE_MISMATCH: still application/xml",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "addNode", "modifier.content", "header", "Content-Type"),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "ct-modifier",
                                "type": "modifier.content",
                                "config": {
                                    "headers": {"Content-Type": "application/json"}
                                },
                            },
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: event-driven/webhook ----
    {
        "failure_mode": "fm-003",  # missing error subprocess (event-driven)
        "archetype": "event-driven-webhook",
        "requirement": "Build a webhook receiver that processes Stripe payment events and updates the order database.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "webhook-payment", "", ""),
                {"flowId": "webhook-payment", "name": "Webhook Payment"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.http",
                                "config": {
                                    "path": "/webhooks/stripe",
                                    "methods": ["POST"],
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added webhook sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "router", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "router",
                                "type": "router",
                                "config": {
                                    "rules": [
                                        {
                                            "condition": "$.type == 'payment.succeeded'",
                                            "target": "succeeded",
                                        }
                                    ]
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added event router",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "succeeded",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://api.example.com/orders",
                                    "method": "PATCH",
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added receiver",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W002: no errorHandling",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [
                                        {"id": "alert-ops", "type": "receiver.mail"}
                                    ]
                                }
                            },
                        }
                    ]
                },
                "applied",
                "Added alert-on-error subprocess",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-004",  # inline secret in webhook signature verification
        "archetype": "event-driven-webhook",
        "requirement": "Build a GitHub webhook receiver that verifies the X-Hub-Signature-256 header.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "github-webhook", "", ""),
                {"flowId": "github-webhook", "name": "GitHub Webhook"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.http",
                                "config": {
                                    "path": "/webhooks/github",
                                    "methods": ["POST"],
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added webhook sender",
            ),
            (
                "resource.write",
                ("resource.write", "write", "script", "verify.groovy", ""),
                {
                    "path": "resources/scripts/verify.groovy",
                    "content": "def secret = 'super-secret-signing-key-from-github'\n"
                    "def sig = message.headers['X-Hub-Signature-256']",
                },
                "applied",
                "Wrote Groovy with INLINE webhook secret",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-E002: inline secret in script",
            ),
        ],
        "correction_actions": [
            (
                "resource.write",
                ("resource.write", "write", "script", "verify.groovy", ""),
                {
                    "path": "resources/scripts/verify.groovy",
                    "content": "def secret = messageExchange.getCredential('github-webhook-secret')\n"
                    "def sig = message.headers['X-Hub-Signature-256']",
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: error-handling-pattern ----
    {
        "failure_mode": "fm-007",  # groovy sandbox violation in error handler
        "archetype": "error-handling-pattern",
        "requirement": "Build an error-handling subprocess that alerts Slack when a flow fails.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "slack-alert", "", ""),
                {"flowId": "slack-alert", "name": "Slack Alert"},
                "applied",
                "Created flow",
            ),
            (
                "resource.write",
                ("resource.write", "write", "script", "alert.groovy", ""),
                {
                    "path": "resources/scripts/alert.groovy",
                    "content": "import java.net.URL\n"
                    "def msg = URLEncoder.encode('Flow failed', 'UTF-8')\n"
                    "new URL('https://slack.com/api/chat.postMessage?text=' + msg).text",
                },
                "applied",
                "Wrote Groovy with java.net.URL (blocked)",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "SANDBOX_VIOLATION: java.net.URL blocked",
            ),
        ],
        "correction_actions": [
            (
                "resource.write",
                ("resource.write", "write", "script", "alert.groovy", ""),
                {
                    "path": "resources/scripts/alert.groovy",
                    "content": "def http = messageExchange.getHttpClient()\n"
                    "def msg = URLEncoder.encode('Flow failed', 'UTF-8')\n"
                    "http.post('https://slack.com/api/chat.postMessage', [text: msg])",
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-003",  # missing error subprocess
        "archetype": "error-handling-pattern",
        "requirement": "Build a flow that retries failed messages with exponential backoff and a dead-letter queue.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "retry-dlq", "", ""),
                {"flowId": "retry-dlq", "name": "Retry + DLQ"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "retry": {"maxAttempts": 3, "backoffMs": 1000}
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added retry receiver",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W002: no errorHandling — failed messages lost",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [
                                        {
                                            "id": "dlq",
                                            "type": "receiver.sftp",
                                            "config": {
                                                "path": "/dlq/${messageId}.json"
                                            },
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                },
                "applied",
                "Added DLQ exception subprocess",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
]


# --------------------------------------------------------------------------- #
# Batch 3: Multi-step corrections (B-005)
# --------------------------------------------------------------------------- #

BATCH_3_SESSIONS = [
    # ---- 3 sessions: corrections requiring 3+ typed actions ----
    {
        "failure_mode": "fm-006",  # dangling edges + missing timeout + missing error handling
        "archetype": "transform-pipeline",
        "requirement": "Insert a logger between sender and transform, add a 30s timeout, and add error handling.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "complex-flow", "", ""),
                {"flowId": "complex-flow", "name": "Complex Flow"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "transform.xml-to-json", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "transform",
                                "type": "transform.xml-to-json",
                            },
                        }
                    ]
                },
                "applied",
                "Added transform",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://backend.example.com",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },  # NO timeout
                "applied",
                "Added receiver WITHOUT timeout",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "DANGLING_EDGE: logger not connected; OIW-W001: missing timeout; OIW-W002: no errorHandling",
            ),
        ],
        "correction_actions": [
            # 1. Add logger
            (
                "flow.patch",
                ("flow.patch", "addNode", "log.message", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "logger", "type": "log.message"},
                        }
                    ]
                },
            ),
            # 2. Rewire edges: sender → logger → transform
            (
                "flow.patch",
                ("flow.patch", "removeEdge", "edge", "sender-transform", ""),
                {
                    "operations": [
                        {"op": "removeEdge", "from": "sender", "to": "transform"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "sender-logger", ""),
                {"operations": [{"op": "addEdge", "from": "sender", "to": "logger"}]},
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "logger-transform", ""),
                {
                    "operations": [
                        {"op": "addEdge", "from": "logger", "to": "transform"}
                    ]
                },
            ),
            # 3. Set timeout on receiver
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.http",
                    "timeoutSeconds",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"timeoutSeconds": 30},
                        }
                    ]
                },
            ),
            # 4. Add error handling
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [{"id": "log-err", "type": "log.message"}]
                                }
                            },
                        }
                    ]
                },
                "applied",
                "Added error subprocess",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-009",  # content-type mismatch + missing error handler + missing timeout
        "archetype": "transform-pipeline",
        "requirement": "Build a SOAP-to-REST flow with XSLT transform, error handling, and proper Content-Type.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "soap-rest", "", ""),
                {"flowId": "soap-rest", "name": "SOAP to REST"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.soap", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.soap"},
                        }
                    ]
                },
                "applied",
                "Added SOAP sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "transform.xslt", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "transform",
                                "type": "transform.xslt",
                                "config": {
                                    "stylesheet": "resources/mappings/soap-to-rest.xsl"
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added XSLT transform",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://api.example.com",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },  # NO ct, NO timeout
                "applied",
                "Added receiver without Content-Type/timeout/errorHandling",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "CONTENT_TYPE_MISMATCH; OIW-W001; OIW-W002",
            ),
        ],
        "correction_actions": [
            # 1. Add Content-Type modifier
            (
                "flow.patch",
                ("flow.patch", "addNode", "modifier.content", "header", "Content-Type"),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "ct-mod",
                                "type": "modifier.content",
                                "config": {
                                    "headers": {"Content-Type": "application/json"}
                                },
                            },
                        }
                    ]
                },
            ),
            # 2. Rewire: transform → ct-mod → receiver
            (
                "flow.patch",
                ("flow.patch", "removeEdge", "edge", "transform-receiver", ""),
                {
                    "operations": [
                        {"op": "removeEdge", "from": "transform", "to": "receiver"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "transform-ct", ""),
                {
                    "operations": [
                        {"op": "addEdge", "from": "transform", "to": "ct-mod"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "ct-receiver", ""),
                {"operations": [{"op": "addEdge", "from": "ct-mod", "to": "receiver"}]},
            ),
            # 3. Set timeout
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.http",
                    "timeoutSeconds",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"timeoutSeconds": 30},
                        }
                    ]
                },
            ),
            # 4. Add error handling
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [{"id": "log-err", "type": "log.message"}]
                                }
                            },
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-002",  # retry without idempotency + missing timeout + missing errorHandling
        "archetype": "api-to-erp",
        "requirement": "Build an idempotent order-posting flow with retry, timeout, and dead-letter queue.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "idempotent-order", "", ""),
                {"flowId": "idempotent-order", "name": "Idempotent Order Post"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://s4.example.com/api/orders",
                                    "method": "POST",
                                    "retry": {"maxAttempts": 5, "backoffMs": 2000},
                                },
                            },
                        }
                    ]
                },  # NO idempotency, NO timeout
                "applied",
                "Added retry receiver without idempotency key or timeout",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W003; OIW-W001; OIW-W002",
            ),
        ],
        "correction_actions": [
            # 1. Add Idempotency-Key header
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "receiver.http", "headers", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {
                                "headers": {"Idempotency-Key": "${header.MessageId}"}
                            },
                        }
                    ]
                },
            ),
            # 2. Set timeout
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.http",
                    "timeoutSeconds",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"timeoutSeconds": 60},
                        }
                    ]
                },
            ),
            # 3. Add DLQ error handling
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [
                                        {
                                            "id": "dlq",
                                            "type": "receiver.sftp",
                                            "config": {"path": "/dlq/"},
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 3 sessions: resource creation + flow patching ----
    {
        "failure_mode": "fm-005",  # missing schema resource + missing validator wiring
        "archetype": "api-validation",
        "requirement": "Build a flow that validates incoming JSON orders against a schema and rejects invalid ones.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "validate-orders", "", ""),
                {"flowId": "validate-orders", "name": "Validate Orders"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.http",
                                "config": {"path": "/orders", "methods": ["POST"]},
                            },
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "validator.json-schema", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "validator",
                                "type": "validator.json-schema",
                                "config": {
                                    "schema": "resources/schemas/order.schema.json"
                                },
                            },
                        }
                    ]
                },  # MISSING file
                "applied",
                "Added validator referencing missing schema",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://backend.example.com",
                                    "method": "POST",
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added receiver",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "RESOURCE_NOT_FOUND: order.schema.json",
            ),
        ],
        "correction_actions": [
            # 1. Create the schema resource
            (
                "resource.write",
                ("resource.write", "write", "schema", "order.schema.json", ""),
                {
                    "path": "resources/schemas/order.schema.json",
                    "content": '{"type":"object","required":["orderId","items"],"properties":{'
                    '"orderId":{"type":"string"},"items":{"type":"array"}}}',
                },
            ),
            # 2. Wire validator between sender and receiver
            (
                "flow.patch",
                ("flow.patch", "removeEdge", "edge", "sender-receiver", ""),
                {
                    "operations": [
                        {"op": "removeEdge", "from": "sender", "to": "receiver"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "sender-validator", ""),
                {
                    "operations": [
                        {"op": "addEdge", "from": "sender", "to": "validator"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "validator-receiver", ""),
                {
                    "operations": [
                        {"op": "addEdge", "from": "validator", "to": "receiver"}
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-007",  # sandbox violation + missing XSLT resource
        "archetype": "transform-pipeline",
        "requirement": "Build a flow with a Groovy enrichment script and an XSLT mapping, both as external resources.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "enrich-map", "", ""),
                {"flowId": "enrich-map", "name": "Enrich + Map"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "script.groovy", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "enricher",
                                "type": "script.groovy",
                                "config": {"script": "resources/scripts/enrich.groovy"},
                            },
                        }
                    ]
                },
                "applied",
                "Added Groovy script node",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "transform.xslt", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "mapper",
                                "type": "transform.xslt",
                                "config": {
                                    "stylesheet": "resources/mappings/transform.xsl"
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added XSLT node",
            ),
            # Inline write the Groovy with blocked import
            (
                "resource.write",
                ("resource.write", "write", "script", "enrich.groovy", ""),
                {
                    "path": "resources/scripts/enrich.groovy",
                    "content": "import java.net.URL\ndef data = new URL('https://api.example.com/ref').text",
                },
                "applied",
                "Wrote Groovy with blocked import",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "SANDBOX_VIOLATION; RESOURCE_NOT_FOUND: transform.xsl",
            ),
        ],
        "correction_actions": [
            # 1. Rewrite the Groovy script safely
            (
                "resource.write",
                ("resource.write", "write", "script", "enrich.groovy", ""),
                {
                    "path": "resources/scripts/enrich.groovy",
                    "content": "def http = messageExchange.getHttpClient()\ndef data = http.get('https://api.example.com/ref').body",
                },
            ),
            # 2. Create the XSLT resource
            (
                "resource.write",
                ("resource.write", "write", "mapping", "transform.xsl", ""),
                {
                    "path": "resources/mappings/transform.xsl",
                    "content": '<?xml version="1.0"?><xsl:stylesheet version="1.0" '
                    'xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template match="/">'
                    "<output/></xsl:template></xsl:stylesheet>",
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-005",  # missing schema + missing error handler
        "archetype": "api-validation",
        "requirement": "Build a flow that validates customer payloads and routes invalid ones to a quarantine queue.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "customer-validate", "", ""),
                {"flowId": "customer-validate", "name": "Customer Validate"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "validator.json-schema", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "validator",
                                "type": "validator.json-schema",
                                "config": {
                                    "schema": "resources/schemas/customer.schema.json"
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added validator (missing schema)",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "RESOURCE_NOT_FOUND; OIW-W002",
            ),
        ],
        "correction_actions": [
            # 1. Create schema
            (
                "resource.write",
                ("resource.write", "write", "schema", "customer.schema.json", ""),
                {
                    "path": "resources/schemas/customer.schema.json",
                    "content": '{"type":"object","required":["customerId"],"properties":{'
                    '"customerId":{"type":"string"},"name":{"type":"string"}}}',
                },
            ),
            # 2. Add error subprocess routing to quarantine
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "errorHandling",
                    "defaultExceptionSubprocess",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "path": "spec.errorHandling",
                            "config": {
                                "defaultExceptionSubprocess": {
                                    "steps": [
                                        {
                                            "id": "quarantine",
                                            "type": "receiver.sftp",
                                            "config": {
                                                "path": "/quarantine/${messageId}.json"
                                            },
                                        }
                                    ]
                                }
                            },
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: edge rewiring ----
    {
        "failure_mode": "fm-006",  # wrong edge target after inserting filter
        "archetype": "transform-pipeline",
        "requirement": "Insert a filter between sender and receiver that drops messages with status 'DRAFT'.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "filter-flow", "", ""),
                {"flowId": "filter-flow", "name": "Filter Flow"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "receiver", "type": "receiver.http"},
                        }
                    ]
                },
                "applied",
                "Added receiver",
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "sender-receiver", ""),
                {"operations": [{"op": "addEdge", "from": "sender", "to": "receiver"}]},
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "filter", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "filter",
                                "type": "filter",
                                "config": {"expression": "$.status != 'DRAFT'"},
                            },
                        }
                    ]
                },  # DID NOT rewire edges
                "applied",
                "Added filter WITHOUT rewiring edges",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "DANGLING_EDGE: filter has no in/out edges",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "removeEdge", "edge", "sender-receiver", ""),
                {
                    "operations": [
                        {"op": "removeEdge", "from": "sender", "to": "receiver"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "sender-filter", ""),
                {"operations": [{"op": "addEdge", "from": "sender", "to": "filter"}]},
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "filter-receiver", ""),
                {"operations": [{"op": "addEdge", "from": "filter", "to": "receiver"}]},
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-006",  # wrong edge target after inserting router
        "archetype": "event-driven-webhook",
        "requirement": "Insert a content-based router between sender and receiver to route orders vs invoices.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "router-flow", "", ""),
                {"flowId": "router-flow", "name": "Router Flow"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "receiver", "type": "receiver.http"},
                        }
                    ]
                },
                "applied",
                "Added receiver",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "router", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "router",
                                "type": "router",
                                "config": {
                                    "rules": [
                                        {
                                            "condition": "$.type == 'order'",
                                            "target": "receiver",
                                        }
                                    ]
                                },
                            },
                        }
                    ]
                },
                "applied",
                "Added router WITHOUT rewiring edges",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "DANGLING_EDGE: router not connected",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "removeEdge", "edge", "sender-receiver", ""),
                {
                    "operations": [
                        {"op": "removeEdge", "from": "sender", "to": "receiver"}
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "sender-router", ""),
                {"operations": [{"op": "addEdge", "from": "sender", "to": "router"}]},
            ),
            (
                "flow.patch",
                ("flow.patch", "addEdge", "edge", "router-receiver", ""),
                {"operations": [{"op": "addEdge", "from": "router", "to": "receiver"}]},
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    # ---- 2 sessions: configuration externalization ----
    {
        "failure_mode": "fm-010",  # hardcoded URL + hardcoded timeout
        "archetype": "api-to-api",
        "requirement": "Build a pass-through flow with all config externalized for dev/stage/prod promotion.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "passthrough", "", ""),
                {"flowId": "passthrough", "name": "Pass-through"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "sender",
                                "type": "sender.http",
                                "config": {"path": "/api/inbox"},
                            },
                        }
                    ]
                },
                "applied",
                "Added sender (hardcoded path)",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.http",
                                "config": {
                                    "url": "https://mytenant.s4.example.com/api",
                                    "method": "POST",
                                    "timeoutSeconds": 30,
                                },
                            },
                        }
                    ]
                },  # hardcoded URL + timeout
                "applied",
                "Added receiver with hardcoded values",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-W005: hardcoded tenant URL + timeout",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "sender.http", "path", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "sender",
                            "config": {"path": "${INBOX_PATH}"},
                        }
                    ]
                },
            ),
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "receiver.http", "url", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"url": "${BACKEND_URL}/api"},
                        }
                    ]
                },
            ),
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.http",
                    "timeoutSeconds",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"timeoutSeconds": "${BACKEND_TIMEOUT:-30}"},
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
    {
        "failure_mode": "fm-004",  # inline secret → credentialRef + externalize URL
        "archetype": "any",
        "requirement": "Build an SMTP notification flow with externalized server URL and credential reference.",
        "failed_steps": [
            (
                "flow.create",
                ("flow.create", "create-flow", "smtp-notify", "", ""),
                {"flowId": "smtp-notify", "name": "SMTP Notify"},
                "applied",
                "Created flow",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "sender.http", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {"id": "sender", "type": "sender.http"},
                        }
                    ]
                },
                "applied",
                "Added sender",
            ),
            (
                "flow.patch",
                ("flow.patch", "addNode", "receiver.mail", "", ""),
                {
                    "operations": [
                        {
                            "op": "addNode",
                            "node": {
                                "id": "receiver",
                                "type": "receiver.mail",
                                "config": {
                                    "to": "ops@example.com",
                                    "subject": "Alert",
                                    "smtpUrl": "smtps://user:pass@smtp.example.com:465",
                                },
                            },
                        }
                    ]
                },  # INLINE SECRET
                "applied",
                "Added mail receiver with inline password",
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
                "failed",
                "OIW-E002: inline secret; OIW-W005: hardcoded URL",
            ),
        ],
        "correction_actions": [
            (
                "flow.patch",
                ("flow.patch", "updateNodeConfig", "receiver.mail", "smtpUrl", ""),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"smtpUrl": "${SMTP_URL}"},
                        }
                    ]
                },
            ),
            (
                "flow.patch",
                (
                    "flow.patch",
                    "updateNodeConfig",
                    "receiver.mail",
                    "credentialRef",
                    "",
                ),
                {
                    "operations": [
                        {
                            "op": "updateNodeConfig",
                            "nodeId": "receiver",
                            "config": {"credentialRef": "smtp-creds"},
                        }
                    ]
                },
            ),
            (
                "flow.validate",
                ("flow.validate", "invoke", "project", "", ""),
                {"strict": True},
            ),
        ],
    },
]


__all__ = ["BATCH_2_SESSIONS", "BATCH_3_SESSIONS"]
