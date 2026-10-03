# Homestead learning export

`export_learning.py` converts the latest ready `20-19` and `40-11` knowledge-base
packs into the bounded JSON consumed by `/api/learning`.

The export also builds the curated `Homebuying journey` course. Its seven stages
and 22 lessons follow the purchase from the decision to buy through the first
year of ownership, with chapter-level readings selected from the same ingested
books. The contract packs remain separate Texas-specific deep dives.

The export deliberately contains focused excerpts, not whole chapters. It keeps
published-book readings separate from Homestead-authored gap briefs and carries
OCR fidelity metadata into the UI.

Generate from the canonical knowledge-base host:

```sh
python3 learning/export_learning.py ~/homestead-kb/homestead_kb.db /tmp/homestead-learning.json
```

Install the result as `/var/lib/homestead/learning/learning.json`, owned by the
`homestead` service account. The generated JSON is private runtime data and is
not committed to this repository.
