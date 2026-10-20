# evals/interpreter: data of the interpreter experiment

Data only: no code runs from here and nothing here imports from `runtime/` (the layer map: `evals/` never reads the runtime's code). The tooling that builds and checks the corpus is `scripts/interpreter_corpus.py`; the code of the interpreter is under `runtime/` (`interpreter*.py`).

| File | What it holds | Owner |
|------|---------------|-------|
| `frame.schema.json` | The schema and the seven rules (`x-rules`) of the frame, the open questions and the last request the interpreter is shown | the corpus package |
| `taxonomy.json` | What the pipeline can have done with a line (`observed`), the order of the outcomes (`severity`), the rules that give a line its category, the metrics and the worked examples | the corpus package |
| `thresholds.json` | The gate: runs, the bounds overall and per language, and the comparison with the current pipeline; frozen when the corpus is | the corpus package |

The interface each file stands for is defined in `SPEC-IX-PHASE1.md` of the plan folder (sections 1.5, 1.8 and 1.9). A file here is canonical JSON of its own kind and changes only with its owner's package. The corpus items and the evidence of the experiment are added here by the packages that own them.
