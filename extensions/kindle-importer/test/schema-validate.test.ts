import { describe, it, expect } from 'vitest';
import { validateExportEnvelope } from '../src/lib/schema-validate';

describe('validateExportEnvelope', () => {
  it('accepts a valid minimal envelope', () => {
    const result = validateExportEnvelope({
      schema_version: '1.0',
      exported_at: '2026-04-29T00:00:00Z',
      source: 'kindle_notebook',
      books: [],
    });
    expect(result.ok).toBe(true);
  });

  it('rejects a missing books field', () => {
    const result = validateExportEnvelope({
      schema_version: '1.0',
      exported_at: '2026-04-29T00:00:00Z',
      source: 'kindle_notebook',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.some((e) => e.message.toLowerCase().includes('books') || e.path.includes('books'))).toBe(true);
    }
  });

  it('rejects a book with no asin', () => {
    const result = validateExportEnvelope({
      schema_version: '1.0',
      exported_at: '2026-04-29T00:00:00Z',
      source: 'kindle_notebook',
      books: [{ title: 'No ASIN', highlights: [] }],
    });
    expect(result.ok).toBe(false);
  });
});
