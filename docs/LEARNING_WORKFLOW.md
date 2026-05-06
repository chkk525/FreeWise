# FreeWise Learning Workflow

FreeWise is the review and memory layer. Do not treat it as a second Notion
workspace or as a permanent archive for every interesting sentence.

The useful split is:

- FreeWise: re-exposure, review, search, triage, and memory reinforcement
- LLM: compression, question generation, comparison, and connection-making
- Notion: durable synthesized notes that are ready to use
- Claude Code: automation and workflow improvements around the above

## Core Loop

1. Read and highlight broadly.
2. Import highlights into FreeWise.
3. Review in FreeWise daily.
4. Use an LLM weekly to convert selected highlights into questions, claims,
   and reusable notes.
5. Promote only synthesized output into Notion.
6. Automate repeated conversion/export steps with Claude Code.

The goal is not to save everything. The goal is to repeatedly encounter useful
ideas until they become usable.

## Capture Tags

Use short note markers while reading. These can live in Kindle/Readwise notes
or be added later inside FreeWise.

| Marker | Meaning | Destination |
|---|---|---|
| `.flash` | A fact, definition, distinction, or model worth memorizing | Anki-style Q/A or spaced recall |
| `.idea` | A concept worth developing in your own words | LLM synthesis, then maybe Notion |
| `.project` | Something directly useful for work, writing, product, code, or decision-making | Notion project note |
| `.notion` | A candidate for durable Notion storage | Notion after cleanup |
| `.quote` | A sentence worth preserving as a quote | Quote file or Notion quote database |

Keep the markers sparse. If every highlight is marked, the markers stop being
useful.

## Daily FreeWise Review

Use `/highlights/ui/review` as the default daily surface.

Keyboard-first review:

- `j` / `Space`: continue to the next highlight
- `f`: favorite something worth returning to
- `d`: discard noise
- `e`: edit note or add a marker
- `?`: show shortcuts

During daily review, classify each highlight mentally:

- Remember: this should become a recall prompt
- Think: this should become a note or claim in your own words
- Use: this belongs to an active project
- Drop: this was interesting once but is no longer useful

Do not over-process during daily review. The daily loop should stay fast enough
that it remains sustainable.

## Weekly LLM Processing

Once a week, process only the valuable subset:

- favorites
- `.flash`
- `.idea`
- `.project`
- `.notion`
- highlights from the same book or theme

Good LLM prompts:

```text
Turn these highlights into:
1. factual recall questions
2. conceptual understanding questions
3. one-sentence claims in my own words
4. possible applications to my current work
5. candidates that deserve a Notion note
```

```text
Cluster these highlights by theme. For each cluster, write:
- the core claim
- the tension or disagreement
- what I should remember
- what I could do with it this week
```

```text
Create Anki-style cards only for items with clear answers.
Avoid cards for vague inspiration or broad opinions.
```

Use LLMs for transformation, not passive summarization. A summary is only
useful when it produces a decision: remember, connect, use, or discard.

## Notion Promotion Rules

Notion is for synthesized knowledge, not raw highlights.

Promote to Notion only when the item becomes one of these:

- Book brief: 3-5 claims from a book, written in your own words
- Concept note: a reusable explanation of one concept
- Project note: something tied to an active goal or deliverable
- Learning map: a topic, what you know, open questions, and next readings
- Essay seed: a claim, example, and possible outline

Avoid copying raw highlight dumps into Notion. They create storage without
memory.

## Claude Code Automation Ideas

Good automation targets:

- Export `.flash` highlights as Anki CSV or Markdown Q/A
- Export `.notion` favorites as Notion-ready Markdown
- Generate a weekly digest of favorites, `.idea`, and `.project` highlights
- Mark exported highlights so they are not processed twice
- Add a FreeWise screen for "Notion promotion candidates"
- Add an LLM prompt template for book briefs and concept notes
- Cluster similar highlights into themes using embeddings
- Track review outcomes: favorited, discarded, mastered, exported

Claude Code should automate friction, not decide what matters. The final
promotion decision should remain human.

## Practical Weekly Routine

Daily, 5 minutes:

1. Open `/highlights/ui/review`.
2. Use `j`, `f`, `d`, `e`.
3. Add markers only when the next action is obvious.

Weekly, 30-45 minutes:

1. Review favorites and marked highlights.
2. Ask the LLM to produce cards, claims, and project applications.
3. Export only the best outputs to Notion.
4. Create Anki-style cards only for clear-answer material.
5. Discard stale or low-signal highlights.

Monthly, 60 minutes:

1. Search by a theme you care about.
2. Ask the LLM to cluster related highlights.
3. Write or update one Notion learning map.
4. Choose the next reading streak around that theme.

## Guiding Principle

FreeWise is where ideas return to your attention.

LLMs help compress and connect those ideas.

Notion is where the few ideas that survive become usable knowledge.
