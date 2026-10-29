# ARTHA — Database ER Design

All tables use a UUID primary key (`id`), `created_at`/`updated_at` timestamps.
Money columns are `NUMERIC(12,2)` — never `FLOAT`.

```
User (1) ──< Expense
User (1) ──< Income
User (1) ──< Category
User (1) ──< Budget
User (1) ──< Goal ──< GoalContribution
User (1) ──< DiaryEntry
User (1) ──< VaultFile
User (1) ──< Notification
User (1) ──< Subscription
User (1) ──< AIChat
User (1) ──< AIInsight
User (1) ──< OTP
User (1) ──< PasswordReset
User (1) ──< RefreshToken
User (1) ──< AuditLog
Category (1) ──< Expense
Category (1) ──< Budget
```

## Phase 1 tables (built now)

### users
| column | type | notes |
|---|---|---|
| id | UUID pk | |
| full_name | varchar(120) | |
| email | varchar(255) unique, indexed | lowercased before storage |
| hashed_password | varchar(255) | Argon2id hash, never plaintext |
| is_verified | boolean default false | flips true after OTP verification |
| is_active | boolean default true | soft-disable |
| failed_login_attempts | int default 0 | reset on success |
| locked_until | timestamptz nullable | account lockout |
| diary_passphrase_hash | varchar(255) nullable | Phase 6 |
| vault_key_salt | varchar(255) nullable | Phase 6 |
| created_at / updated_at | timestamptz | |

### otps
| column | type | notes |
|---|---|---|
| id | UUID pk | |
| user_id | UUID fk → users | |
| code_hash | varchar(255) | OTP is hashed at rest, not stored plaintext |
| purpose | varchar(30) | `email_verification` \| `login_2fa` \| `password_reset` |
| expires_at | timestamptz | now() + 5 minutes |
| attempts | int default 0 | max 5, then must resend |
| consumed_at | timestamptz nullable | one-time use |
| created_at | timestamptz | |

### password_resets
| id, user_id, token_hash, expires_at, consumed_at, created_at |

### refresh_tokens
| id, user_id, token_hash, expires_at, revoked_at, user_agent, ip_address, created_at |

### audit_logs
| id, user_id nullable, event_type, ip_address, user_agent, metadata (JSONB), created_at |
Events: `login_success`, `login_failed`, `account_locked`, `password_reset_requested`,
`otp_verified`, `diary_unlocked`, `vault_unlocked`, etc. — this is what powers the
"Recent account activity" panel already in `settings.html`.

## Later-phase tables (referenced now so FKs are stable, not built until their phase)

`categories`, `expenses`, `incomes`, `budgets`, `goals`, `goal_contributions`,
`diary_entries`, `vault_files`, `notifications`, `subscriptions`, `ai_chats`, `ai_insights`
— schemas are sketched in `docs/03-api-design.md` per-phase so the eventual model fields
match the endpoints exactly instead of guessing ahead.
