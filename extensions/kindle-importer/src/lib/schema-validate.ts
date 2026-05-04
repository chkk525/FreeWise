// Hand-rolled validator for the Kindle export envelope. We can't use Ajv
// here because it compiles schemas at runtime via `new Function(...)`, and
// content scripts inherit the host page's CSP — read.amazon.com forbids
// `unsafe-eval`, so Ajv crashes with "Evaluating a string as JavaScript
// violates the following Content Security Policy directive". The schema is
// small and stable, so an inline validator is cheaper than wiring up Ajv's
// standalone code generation through the build.
//
// Mirrors `shared/kindle-export-v1.schema.json` — keep them in sync.

export type ValidationError = { path: string; message: string };
export type ValidationResult =
  | { ok: true }
  | { ok: false; errors: ValidationError[] };

const SCHEMA_VERSION_RE = /^1\.[0-9]+$/;
const ISO_DATETIME_RE =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const COLORS = new Set(['yellow', 'blue', 'pink', 'orange']);

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function pushType(
  errors: ValidationError[],
  path: string,
  expected: string,
): void {
  errors.push({ path, message: `must be ${expected}` });
}

function checkStringOrNull(
  errors: ValidationError[],
  path: string,
  value: unknown,
): void {
  if (value === null || value === undefined) return;
  if (typeof value !== 'string') pushType(errors, path, 'string or null');
}

function checkIntegerOrNull(
  errors: ValidationError[],
  path: string,
  value: unknown,
): void {
  if (value === null || value === undefined) return;
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    pushType(errors, path, 'integer or null');
  }
}

function checkHighlight(
  errors: ValidationError[],
  path: string,
  value: unknown,
): void {
  if (!isObject(value)) {
    pushType(errors, path, 'object');
    return;
  }
  if (typeof value.id !== 'string' || value.id.length < 1) {
    errors.push({ path: `${path}/id`, message: 'must be non-empty string' });
  }
  if (typeof value.text !== 'string') {
    pushType(errors, `${path}/text`, 'string');
  }
  checkStringOrNull(errors, `${path}/note`, value.note);
  if (value.color !== undefined && value.color !== null) {
    if (typeof value.color !== 'string' || !COLORS.has(value.color)) {
      errors.push({
        path: `${path}/color`,
        message: 'must be one of yellow, blue, pink, orange or null',
      });
    }
  }
  checkIntegerOrNull(errors, `${path}/location`, value.location);
  checkIntegerOrNull(errors, `${path}/page`, value.page);
  if (value.created_at !== undefined && value.created_at !== null) {
    if (
      typeof value.created_at !== 'string' ||
      !ISO_DATETIME_RE.test(value.created_at)
    ) {
      errors.push({
        path: `${path}/created_at`,
        message: 'must be ISO date-time string or null',
      });
    }
  }
}

function checkBook(
  errors: ValidationError[],
  path: string,
  value: unknown,
): void {
  if (!isObject(value)) {
    pushType(errors, path, 'object');
    return;
  }
  if (typeof value.asin !== 'string' || value.asin.length < 1) {
    errors.push({ path: `${path}/asin`, message: 'must be non-empty string' });
  }
  if (typeof value.title !== 'string' || value.title.length < 1) {
    errors.push({ path: `${path}/title`, message: 'must be non-empty string' });
  }
  checkStringOrNull(errors, `${path}/author`, value.author);
  checkStringOrNull(errors, `${path}/cover_url`, value.cover_url);
  if (!Array.isArray(value.highlights)) {
    pushType(errors, `${path}/highlights`, 'array');
  } else {
    value.highlights.forEach((h, i) => {
      checkHighlight(errors, `${path}/highlights/${i}`, h);
    });
  }
}

export function validateExportEnvelope(payload: unknown): ValidationResult {
  const errors: ValidationError[] = [];

  if (!isObject(payload)) {
    return {
      ok: false,
      errors: [{ path: '(root)', message: 'must be object' }],
    };
  }

  if (
    typeof payload.schema_version !== 'string' ||
    !SCHEMA_VERSION_RE.test(payload.schema_version)
  ) {
    errors.push({
      path: '/schema_version',
      message: 'must match pattern ^1\\.[0-9]+$',
    });
  }
  if (
    typeof payload.exported_at !== 'string' ||
    !ISO_DATETIME_RE.test(payload.exported_at)
  ) {
    errors.push({
      path: '/exported_at',
      message: 'must be ISO date-time string',
    });
  }
  if (payload.source !== 'kindle_notebook') {
    errors.push({
      path: '/source',
      message: 'must be const "kindle_notebook"',
    });
  }
  if (!Array.isArray(payload.books)) {
    pushType(errors, '/books', 'array');
  } else {
    payload.books.forEach((b, i) => {
      checkBook(errors, `/books/${i}`, b);
    });
  }

  return errors.length === 0 ? { ok: true } : { ok: false, errors };
}
