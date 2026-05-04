import Ajv2020, { type ErrorObject } from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import schema from '../../../../shared/kindle-export-v1.schema.json';

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile(schema);

export type ValidationError = { path: string; message: string };

export type ValidationResult =
  | { ok: true }
  | { ok: false; errors: ValidationError[] };

export function validateExportEnvelope(payload: unknown): ValidationResult {
  if (validate(payload)) return { ok: true };
  const errors: ValidationError[] = (validate.errors ?? []).map((e: ErrorObject) => ({
    path: e.instancePath || e.schemaPath || '(root)',
    message: e.message ?? 'unknown error',
  }));
  return { ok: false, errors };
}
