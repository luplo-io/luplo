-- demos/fixtures/seed.sql
--
-- Deterministic seed data for demos/recall.tape and demos/impact.tape.
-- Fixed IDs ensure the gifs show identical 8-char prefixes on every run.
--
-- Prereqs:
--   - Run against a fresh `luplo_demos` database (see demos/README.md)
--   - alembic migrations already applied

-- ── Project + actor ──────────────────────────────────────────────

INSERT INTO projects (id, name, description) VALUES
    ('demos', 'luplo demos', 'Fixture project for the README demos')
ON CONFLICT (id) DO NOTHING;

INSERT INTO actors (id, name, email) VALUES
    ('00000000-0000-0000-0000-0000000d1a5c', 'Demo Actor', 'demo@luplo.io')
ON CONFLICT (id) DO NOTHING;

-- ── Work unit ─────────────────────────────────────────────────────

INSERT INTO work_units (id, project_id, title, description, status, created_by)
VALUES (
    'demos-websocket',
    'demos',
    'Realtime transport choice',
    'A small decision tree around WebSocket vs gRPC.',
    'in_progress',
    '00000000-0000-0000-0000-0000000d1a5c'
)
ON CONFLICT (id) DO NOTHING;

-- ── Decision items ────────────────────────────────────────────────
-- Fixed IDs make the 8-char prefixes stable across renders.

INSERT INTO items (
    id, project_id, item_type, title, body, rationale,
    actor_id, work_unit_id, search_tsv
) VALUES
    (
        'dec00023-0000-0000-0000-000000000000', 'demos', 'decision',
        'WebSocket over gRPC for realtime transport',
        'Use WebSocket as the realtime transport, not gRPC streams.',
        'Browser clients first; gRPC needs envoy proxy to reach the browser.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple',
            'WebSocket over gRPC realtime transport Browser clients gRPC envoy proxy')
    ),
    (
        'dec00031-0000-0000-0000-000000000000', 'demos', 'decision',
        'Nakama proxy design',
        'Run Nakama behind a TLS-terminating proxy; reuse the WebSocket session.',
        'Single ingress simplifies auth; session affinity required for state.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple', 'Nakama proxy design WebSocket session auth')
    ),
    (
        'dec00038-0000-0000-0000-000000000000', 'demos', 'decision',
        'Client network layer: thin wrapper',
        'Wrap the WebSocket in a thin Observable layer; no heavy state sync library.',
        'We control the protocol; a sync library would just be overhead.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple', 'Client network layer thin wrapper Observable WebSocket')
    ),
    (
        'dec00041-0000-0000-0000-000000000000', 'demos', 'decision',
        'Reconnect policy: exponential backoff, cap at 30s',
        'Exponential backoff 1s → 30s, then jitter. Session resume on reconnect.',
        'Avoid thundering herd after incident; preserve partial state.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple', 'Reconnect policy exponential backoff jitter session resume')
    ),
    (
        'dec00045-0000-0000-0000-000000000000', 'demos', 'decision',
        'Load balancer: envoy in front of Nakama proxy',
        'Envoy terminates TLS, forwards WebSocket frames with sticky sessions.',
        'Nakama proxy expects stable upstream; envoy gives us health checks.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple', 'Load balancer envoy TLS Nakama sticky sessions')
    ),
    (
        'dec00012-0000-0000-0000-000000000000', 'demos', 'decision',
        'SQLite for single-tenant persistence (superseded)',
        'SQLite is sufficient for single-user state.',
        'Fast enough, no ops overhead.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple', 'SQLite single-tenant persistence')
    ),
    (
        'dec00047-0000-0000-0000-000000000000', 'demos', 'decision',
        'Postgres over SQLite',
        'Switch the primary store to Postgres; SQLite remains for local dev.',
        'Multi-user writes; pgvector needed for semantic rerank.',
        '00000000-0000-0000-0000-0000000d1a5c',
        'demos-websocket',
        to_tsvector('simple',
            'Postgres over SQLite multi-user writes pgvector semantic rerank')
    )
ON CONFLICT (id) DO NOTHING;

-- Supersedes chain: dec00047 supersedes dec00012.
UPDATE items
    SET supersedes_id = 'dec00012-0000-0000-0000-000000000000'
    WHERE id = 'dec00047-0000-0000-0000-000000000000';

-- ── Typed edges (the graph `lp impact` traverses) ────────────────

INSERT INTO links (from_item_id, to_item_id, link_type, note, created_by_actor_id)
VALUES
    -- dec00023 (WebSocket) blocks the three downstream decisions.
    ('dec00023-0000-0000-0000-000000000000',
     'dec00031-0000-0000-0000-000000000000', 'depends',
     'Nakama proxy design presumes WebSocket is the transport.',
     '00000000-0000-0000-0000-0000000d1a5c'),
    ('dec00023-0000-0000-0000-000000000000',
     'dec00038-0000-0000-0000-000000000000', 'depends',
     'Client network layer wraps the WebSocket chosen above.',
     '00000000-0000-0000-0000-0000000d1a5c'),
    ('dec00023-0000-0000-0000-000000000000',
     'dec00041-0000-0000-0000-000000000000', 'depends',
     'Reconnect policy presumes WebSocket session semantics.',
     '00000000-0000-0000-0000-0000000d1a5c'),
    -- dec00031 (Nakama proxy) blocks dec00045 (load balancer).
    ('dec00031-0000-0000-0000-000000000000',
     'dec00045-0000-0000-0000-000000000000', 'depends',
     'Load balancer must speak to the Nakama proxy specifically.',
     '00000000-0000-0000-0000-0000000d1a5c')
ON CONFLICT DO NOTHING;
