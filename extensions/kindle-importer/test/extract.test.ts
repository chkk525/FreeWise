import { describe, it, expect } from 'vitest';
import { Window } from 'happy-dom';
import { readFileSync } from 'fs';
import { resolve } from 'path';

import { extractCurrentBookHighlights, extractLibrary } from '../src/lib/kindle-extract';

const fixture = readFileSync(
  resolve(__dirname, 'fixtures/notebook-en.html'),
  'utf-8'
);

function parseFixture(): Document {
  const win = new Window();
  win.document.write(fixture);
  return win.document as unknown as Document;
}

describe('extractCurrentBookHighlights', () => {
  it('returns the highlights present on the page', () => {
    const doc = parseFixture();
    const highlights = extractCurrentBookHighlights(doc);
    expect(highlights).toHaveLength(2);
    expect(highlights[0]).toMatchObject({
      id: 'QID:1',
      text: 'First highlight text.',
      color: 'yellow',
      location: 100,
    });
    expect(highlights[1]).toMatchObject({
      id: 'QID:2',
      text: 'Second highlight.',
      note: 'A user note.',
      color: 'blue',
      location: 250,
    });
  });

  it('returns an empty array when there is no annotation container', () => {
    const win = new Window();
    win.document.write('<html><body><p>nothing</p></body></html>');
    const highlights = extractCurrentBookHighlights(
      win.document as unknown as Document
    );
    expect(highlights).toEqual([]);
  });
});

describe('extractLibrary', () => {
  it('returns the library books with empty highlights array', () => {
    const doc = parseFixture();
    const books = extractLibrary(doc);
    expect(books).toHaveLength(1);
    expect(books[0]).toMatchObject({
      asin: 'B07TEST1',
      title: 'Test Book One',
      author: 'Test Author One',
      cover_url: 'https://example.com/cover1.jpg',
      highlights: [],
    });
  });
});
