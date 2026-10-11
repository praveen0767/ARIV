# Draft submission note — revise to match the artifact actually deployed

**Fan problem:** When fans return to a cricket match after a break, the score tells them where the game is, but not how it got there. Reading several overs of commentary to recover the missing context is effortful.

**Solution:** MatchLens lets a fan select a historical match interval and a team/player perspective. It reconstructs the interval from ball-by-ball data, calculates the score-state change deterministically, selects important events, and produces a concise explanation with inspectable evidence. The explanation can be localized to the supported language, while the underlying match facts remain unchanged. If AI is unavailable or its output fails validation, a deterministic recap remains available. Historical replay is clearly labelled.

**AI tools used:** [Name only the models/tools actually used in the deployed artifact, e.g. the specific LLM provider/model, plus any coding assistant if the assignment asks for it.]

**Artifact:** [Insert the publicly accessible working URL.]

This note is a draft. Do not submit until the product URL works in a fresh session, the described language/model are actually implemented, and the tests/data attribution have been verified.
