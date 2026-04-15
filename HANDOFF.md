# luplo 구현 핸드오프 — v0.5.1 → v0.5.3

작성: 2026-04-15. 새 Claude Code 세션이 이 문서 + luplo DB의 items를 읽고 바로 구현 시작할 수 있도록.

---

## 참조 방법

```bash
lp brief --project luplo
lp work resume "v0.5.1 auth" --project luplo         # WU3
lp work resume "tasks/qa" --project luplo            # WU2
lp items search "<keyword>" --project luplo
```

상세 스펙 전부 luplo items에 담겨있음. 이 문서는 entry point.

---

## 스프린트 순서 (재조정됨 2026-04-15)

| | 기존 | 신규 |
|---|---|---|
| v0.5 | ✅ 12 테이블 완성 | ✅ 유지 |
| v0.5.1 | tasks | **auth** ← 순서 앞당김 |
| v0.5.2 | qa | **tasks** |
| v0.5.3 | — | **qa** |

이유: actors.id TEXT → UUID 전환이 모든 FK 영향. auth 먼저 확정해야 tasks/qa 구현 시 actor_id 안정. 또 사용자가 pw 기반 빠른 테스트 원함.

---

## 스프린트 1 — v0.5.1 auth

**Work Unit**: `v0.5.1 auth 구현 — lp login + actors 재설계 (tasks/qa 선행)`
**WU ID**: `e4710766-976e-4203-a65f-7a22e0d67e14`

### 목표

- `lp login` (Loopback + PKCE)
- OAuth (GitHub + Google) — magic link v0.6+ deferral
- Password 로그인 최소 구현 (argon2, 재설정 flow 없음)
- actors 재설계 (UUID + email 강제 + SaaS 필드 + password_hash)
- 서버 설정 체계 (pydantic-settings + TOML + env)
- 이메일 도메인 필터
- Local 모드 `.luplo[actor]` 유지 (UUID string + email)

### 구현 순서

1. `src/luplo/server/config.py` (pydantic-settings + TOML + env)
2. `alembic 0002_auth_redesign.py` — actors UUID + 확장 + FK 10개 전환
3. `src/luplo/server/auth/password.py` (argon2)
4. `src/luplo/server/auth/jwt.py` (HS256)
5. `src/luplo/server/auth/pkce.py`
6. `src/luplo/server/auth/oauth.py` (authlib GitHub/Google, enabled 조건부)
7. `src/luplo/server/auth/domain_filter.py`
8. `src/luplo/server/routes/auth.py` (엔드포인트 전부)
9. `src/luplo/server/auth/templates/login.html` + `login.css` (최소)
10. `src/luplo/server/app.py` — lifespan에 `ensure_admin()` + worker
11. `src/luplo/cli.py` — `lp login / logout / whoami / token refresh`
12. `src/luplo/cli.py` — `lp admin set-password`
13. `src/luplo/cli.py` — `lp server init-secrets / config-check`
14. `lp init` Local 모드 — UUID + email prompt
15. end-to-end 검증

### 성공 기준

1. ✅ `lp login` 브라우저 GitHub → 토큰 keyring 저장
2. ✅ `lp login` 브라우저 Google → 토큰 keyring 저장
3. ✅ email + password `/auth/login` → JWT
4. ✅ `allowed_email_domains` 설정 → 비허용 도메인 403
5. ✅ `allow_auto_create=false` → 미등록 OAuth 사용자 403
6. ✅ `LUPLO_ADMIN_EMAIL + LUPLO_ADMIN_PASSWORD` seed → 서버 시작 시 admin 자동 생성
7. ✅ `.luplo[actor]` Local 모드 그대로 작동 (UUID + email)
8. ✅ 모든 기존 tests 회귀 0 (actor_id fixture UUID로 업데이트)

### 관련 items (WU3, 10개)

- 구현 순서 재조정 (auth → tasks → qa)
- 서버 설정 체계 (pydantic-settings + TOML + env)
- actors 재설계 (UUID + email 강제 + password_hash + SaaS 필드)
- lp login flow (Loopback + PKCE + keyring)
- OAuth (GitHub + Google), magic link v0.6+
- password 로그인 최소 구현 (argon2, admin seed, 재설정 없음)
- auth 정책 (auto_create + 도메인 필터)
- auth routes + 로그인 페이지 + 파일 구조
- FK UUID 전환 영향 범위 (10개 컬럼)
- Local 모드 `.luplo[actor]` 유지

### 주의사항

- **현재 actors 데이터 확인 필수** 전에: `psql $LUPLO_DB_URL -c "SELECT id, email, name FROM actors;"`
- email NULL 존재 시 placeholder 전략 결정 (`{old_id}@placeholder.local` 매핑 + migration_notes_0002.md에 기록)
- 기존 tests fixture의 `actor_id="ryan"` 류 전부 UUID로 교체

---

## 스프린트 2 — v0.5.2 tasks

**Work Unit**: `tasks/qa_checks 스키마 인계 (v0.5.1 → v0.5.2)`  ※ 제목의 버전 번호는 재조정 전 것 — 실제는 v0.5.2/v0.5.3
**WU ID**: `8a49a6b1-5f93-45ce-ace7-c7c717bc525b`

### 목표

tasks 테이블 + CRUD + CLI + MCP + block_task 자동 decision item 승격.

### 스키마

WU2의 "tasks 재도입 (v0.5.1) — 12→13 테이블" item body에 전체 SQL. 핵심:

- `work_unit_id NOT NULL REFERENCES work_units(id)` — 떠있는 task 금지
- `UNIQUE WHERE status='in_progress'` — work_unit당 동시 1개
- `sort_order NOT NULL` — gap 10, 20, 30... 전략
- `CHECK (status IN ('pending','in_progress','done','blocked','skipped'))`

### 구현 순서 10단계

1. alembic 0003_add_tasks.py (0002 뒤)
2. models.py Task dataclass
3. core/tasks.py + tests/test_tasks.py (~14 tests)
4. core/backend/protocol.py (task 시그니처)
5. core/backend/local.py (task 메서드 + audit + block→decision cross-cutting)
6. cli.py — `lp task` 명령 그룹 10개 (~6 tests via CliRunner)
7. mcp.py — 5개 task 도구 (~4 tests)
8. `luplo_work_resume` 응답에 tasks 포함 (JSON shape 준수)
9. `close_work_unit(force=False)` — in_progress task 있으면 경고
10. 수동 검증 (lp work open → task add → start → done)

### 주요 결정 포인트

- **actor_id: str (UUID string) 모든 mutating 함수에 필수** — core는 순수 CRUD, 검증은 경계
- **block_task → decision item 자동 생성** — LocalBackend cross-cutting (core/tasks.py 아님)
  - item 필드 상속: `work_unit_id=task.work_unit_id`, `system_ids=task.context.get("systems", [])`, `source_ref=f"task_block:{task_id}"`, `tags=['task_block']`
- **UniqueViolation → TaskAlreadyInProgressError** (친화 에러 컨벤션)
- **items.py 변경 없음** — item_type에 'task' 추가 X (3층 분리 원칙)

### 성공 기준

1. ✅ `lp work open "X"` → `lp task add "T1"` → `lp task start` → `lp task done --summary "..."`
2. ✅ 다른 세션에서 `lp work resume "X"` → tasks 복원
3. ✅ `lp task blocked T3 --reason "..."` → decision item 자동 생성 + work_unit_id/system_ids 상속
4. ✅ `close_work_unit` with in_progress task → 경고 (force=True로 강제 마감)
5. ✅ ~26 new tests 통과, 기존 tests 회귀 0

### 관련 items (WU2)

- tasks 재도입 (12→13 테이블, 스키마 SQL)
- tasks core 함수 spec (actor_id 필수, 9개 함수)
- tasks CLI 10개 + MCP 5개
- tasks 기존 코드 수정 포인트 + 구현 순서 10단계
- tasks deferral + 성공 기준
- block_task → decision item 자동 생성
- block_task 자동 decision item 상속 규칙
- task done → 새 item 승격 (v0.5.2 수동, v0.6 LLM)
- items / tasks / qa_checks 3층 분리 — 통합 금지
- 친화 에러 컨벤션 — core/exceptions.py

---

## 스프린트 3 — v0.5.3 qa

**Work Unit**: 스프린트 2와 동일 WU2 (`8a49a6b1-...`)

### 목표

qa_checks 테이블 + CRUD + CLI + MCP + supersede → qa 재검증 자동 (시나리오 9번째 단계).

### 스키마

WU2의 "qa_checks 도입 (v0.5.2) — 13→14 테이블" item body에 전체 SQL. 핵심:

- `work_unit_id` **nullable** (크로스-work_unit QA 허용)
- `target_task_ids TEXT[]` + `target_item_ids TEXT[]` — N:M을 배열로
- `CHECK (status IN (...))` 6개 status, `CHECK (coverage IN (...))` 2개
- GIN 인덱스 3개 (target_task_ids, target_item_ids, areas)

### 구현 순서 8단계

1. alembic 0004_add_qa_checks.py (0003 뒤)
2. models.py QACheck dataclass
3. core/qa.py + tests/test_qa.py (~14 tests)
4. **core/backend/local.py `create_item` wrapper에 재검증 트리거** (← core/items.py 아님! 중요)
5. core/backend/local.py qa 메서드 + audit
6. cli.py — `lp qa` 명령 8개 (~6 tests) + `lp qa dump --format markdown`
7. mcp.py — 4개 qa 도구 (~4 tests) + `luplo_work_resume` 응답 qa 포함
8. `luplo_task_done` 확장 — 간단 프롬프트로 human_only qa 제안 (v0.5.3 선택)

### 주요 결정 포인트

- **재검증 트리거 = LocalBackend** (QA 인계문서 §4.3 "core/items.py에서"는 정정됨)
  ```sql
  UPDATE qa_checks SET status='pending', updated_at=now()
  WHERE :old_item_id = ANY(target_item_ids) AND status='passed';
  ```
  + audit_log에 `qa.revalidate` 기록
- **N:M은 배열 + GIN** — links 건들지 않음 (본래 용도 보존)
- **assign_qa(actor_id, assignee_id)** 파라미터 분리 (행위자 ≠ 할당 대상)

### 성공 기준

1. ✅ task done → `lp qa add "T vfx 체크" --tasks T3,T5 --area vfx`
2. ✅ 양방향 조회 — `lp qa ls --task T3` (GIN 역조회)
3. ✅ `lp qa dump --format markdown` → QA 엔지니어 인계 문서
4. ✅ item supersede → 관련 passed qa 자동 pending + `qa.revalidate` audit
5. ✅ `lp work resume` → pending qa 요약 (JSON shape 준수)
6. ✅ ~24 new tests 통과, 기존 tests 회귀 0

### 관련 items (WU2)

- qa_checks 도입 (13→14 테이블, 스키마 SQL)
- qa_checks N:M은 배열 + GIN — links 건들지 않음
- qa core 함수 spec 10개 (actor_id 필수, assign_qa 파라미터 분리)
- qa CLI 8개 + MCP 4개 + 기존 수정 포인트 + dump 템플릿
- qa v0.5.2 deferral + 성공 기준 + 구현 순서 (재검증 알림 v0.6+)
- 재검증 트리거 위치 = LocalBackend (QA 인계 §4.3 정정)
- item supersede → 관련 passed qa_checks 자동 pending (9번째 단계)
- qa_checks.areas 7종 (vfx/sfx/ux/edge_case/perf/a11y/sec)
- qa_checks.coverage 2종 (auto_partial / human_only)

---

## 교차 원칙 (전 스프린트 공통)

### 아키텍처

- **items / tasks / qa_checks 3층 분리** — 각자 자기 테이블. 통합 유혹 금지.
- **core/는 순수 CRUD** — 단일 테이블 연산만. audit/history 의존 X.
- **LocalBackend가 cross-cutting** — audit_log 기록, items_history 기록, block_task→decision, supersede→qa 재검증 모두 여기.
- **RemoteBackend는 HTTP wrapper** — core 함수를 REST로 노출.

### actor_id 전달 경로

- `actor_id: str (UUID string)` 파라미터로 core에 전달
- Local: `.luplo[actor].id` 읽어 CLI/MCP가 주입
- Remote: JWT sub → FastAPI `Depends(get_current_actor)` → 라우트 → core

### 에러 컨벤션

- `core/exceptions.py` 단일 파일
- `LuploError` 베이스 클래스 (`http_status: int` 힌트)
- `NotFoundError` (404), `ConflictError` (409), `ValidationError` (400), `AuthError` (401/403)
- 도메인별: `TaskNotFoundError`, `TaskAlreadyInProgressError`, `QACheckNotFoundError`, ...
- psycopg IntegrityError/UniqueViolation 등은 core 경계에서 도메인 에러로 변환

### alembic 순서

```
0001_init_schema         (v0.5, 12 테이블) ✅
0002_auth_redesign       (v0.5.1, actors UUID + FK 10개 전환)
0003_add_tasks           (v0.5.2)
0004_add_qa_checks       (v0.5.3)
```

`alembic upgrade head`로 자동 순차 적용.

### 마이그레이션 간 의존

- 0002 → 0003: actors UUID 완성 후 tasks의 FK 설계
- 0003 → 0004: tasks 존재 후 qa_checks.target_task_ids 의미 성립 (FK 아님, 의미 의존만)

### audit_log action 표준

```
item.create / item.update / item.delete
task.create / task.start / task.complete / task.block / task.skip / task.update / task.reorder
qa.create / qa.start / qa.pass / qa.fail / qa.block / qa.skip / qa.assign / qa.update / qa.revalidate
auth.login / auth.logout / auth.reject
```

`{domain}.{verb}` 패턴. 일관 유지.

### `luplo_work_resume` 응답 JSON shape

```json
{
  "work_units": [
    {
      "id": "uuid",
      "title": "...",
      "items": [...],
      "tasks": {
        "in_progress": {...} | null,
        "pending_next": [...]
      },
      "qa_checks": {
        "pending": [...],
        "failed": [...]
      }
    }
  ]
}
```

Top-level 키만 합의. 배열 안 객체 필드는 구현자 재량.

---

## 검증 명령 (각 스프린트 끝)

```bash
uv run pytest -v                                  # 전체 통과
uv run ruff check . && uv run ruff format .        # 0 warnings
uv run pyright src/                                # strict, no type: ignore
alembic upgrade head && alembic downgrade base && alembic upgrade head  # 양방향 검증
```

---

## 참조 순서

1. **이 문서** (HANDOFF.md) — entry point
2. `lp brief --project luplo` — active WU + recent items
3. `lp work resume "<keyword>"` — 관련 work_unit의 items 전부 로드
4. `lp items search "<keyword>"` — 특정 주제 검색
5. 노션 원본 (상위 맥락 필요 시):
   - Luplo — 철학 & 진화 단계
   - Luplo (lp) — v0.5 Design
   - Tasks 재도입 인계 (원문은 "v0.5 → v0.5.1", 재조정 후 v0.5.1 → v0.5.2)
   - QA Checks 도입 인계 (원문은 "v0.5.1 → v0.5.2", 재조정 후 v0.5.2 → v0.5.3)

---

## 변경 로그

- 2026-04-15: 최초 작성
  - WU2 (tasks/qa) 23 items + WU3 (auth) 10 items 박음
  - v0.5.1/v0.5.2 순서 재조정 (auth 선행)
  - Magic link v0.6+로 deferral
  - Password 로그인 최소 구현 포함
