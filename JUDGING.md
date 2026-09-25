# Judging

**Not implemented.** This build stops at T1. There is no judge assignment, no rubric, no scoring UI, no cross-judge normalization, no organizer progress dashboard, and no per-stage CSV export.

`.dogfood.toml` claims T1 only.

## What happens to score rows today

If `fixtures/fixtures.json` contains a `scores` array (or `judgements` / `judgments`), those rows are stored in `retained_scores` so the import is not lossy. A `criteria` object such as `{functionality, quality, innovation}` is expanded into one row per criterion. The original object stays on the payload. They are not shown on any page, not returned to participants or judges, and not turned into a ranking. The organizer JSON export includes them under `retained_scores_unprocessed` and labels them as raw import rows, not results.

A judge account can log in and read the public gallery. A judge cannot open another person's submission editor, cannot join a team, and cannot read a score API. There is no score API. `GET /e/{slug}/scores` is a 404.

## Not a method

Nothing in this build averages scores, weights criteria, or calibrates judges. Writing a formula here would be a claim about software that does not exist. Normalization and pairwise ranking are T2 work and are intentionally absent.
