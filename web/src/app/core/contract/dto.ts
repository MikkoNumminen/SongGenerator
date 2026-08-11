// Generated from the edge's OpenAPI schema. Do not edit by hand.
//
// Regenerate after changing any response model in api/app/main.py:
//
//     python api/tools/dump_openapi.py  web/src/app/core/contract/openapi.json
//     python api/tools/generate_dtos.py web/src/app/core/contract/openapi.json \
//                                       web/src/app/core/contract/dto.ts
//
// A hand-edit here is a lie about what the server sends, and it will be
// overwritten. Change the Python model instead.

/**
 * One bank, as `banks.BankInfo` reports it plus the derived verdict.
 */
export interface BankReply {
  built: boolean;
  directory: string;
  name: string;
  problem?: string | null;
  standardised: boolean;
  units: number;
  usable: boolean;
}

export interface BanksReply {
  any_usable: boolean;
  banks: Array<BankReply>;
  engines: Array<string>;
  levels: Array<string>;
}

export interface CancelReply {
  cancelled: boolean;
}

/**
 * One finished rendering, as something to download.
 */
export interface FileReply {
  bytes: number;
  level?: string | null;
  name: string;
}

export interface FilesReply {
  files: Array<FileReply>;
}

export interface GrantRequest {
  email: string;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

/**
 * What an unauthenticated caller may learn. Deliberately nothing else.
 */
export interface HealthReply {
  auth_configured: boolean;
  busy: boolean;
  status: string;
}

export interface HistoryReply {
  jobs: Array<JobReply>;
}

/**
 * A run as reported. Mirrors `jobs.Job` without the arrangement.
 *
 * The pasted arrangement can be enormous and nothing renders it back, so it
 * stays in the store for re-running rather than riding on every poll.
 */
export interface JobReply {
  bank: string;
  created_at: string;
  detail?: string | null;
  engine?: string | null;
  error?: string | null;
  exit_code?: number | null;
  finished_at?: string | null;
  id: string;
  level?: string | null;
  mimicry?: number | null;
  output_dir?: string | null;
  percent?: number | null;
  requested_by: string;
  settled: boolean;
  song?: string | null;
  source_url: string;
  stage: string;
  started_at?: string | null;
}

export interface LibraryReply {
  tracks: Array<TrackReply>;
}

/**
 * A request to make a song.
 *
 * Validated here as well as in the browser. The browser's validation is for
 * the person typing; this one is because the browser is not the only thing
 * that can post to this.
 */
export interface SubmitBody {
  arrangement?: string | null;
  bank: string;
  engine?: string | null;
  level?: string | null;
  mimicry?: number | null;
  source_url: string;
}

/**
 * One playable rendering, addressed by where it sits on disk.
 */
export interface TrackReply {
  bank: string;
  bytes: number;
  level?: string | null;
  name: string;
  song: string;
}

export interface UserReply {
  added_at: string;
  added_by: string;
  email: string;
  is_admin: boolean;
}

export interface UsersReply {
  admins: Array<string>;
  users: Array<UserReply>;
}

export interface ValidationError {
  ctx?: Record<string, unknown>;
  input?: unknown;
  loc: Array<string | number>;
  msg: string;
  type: string;
}
