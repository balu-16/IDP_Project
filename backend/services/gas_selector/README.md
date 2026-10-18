# Application GAS kernels

`primitives.py`, `baseline.py`, and `refinement.py` are snapshots of the verified
research kernels. Only their package imports differ. `ORIGINS.json` records
both original and application-file checksums. The application does not import
dataset loaders, experiment runners, or judgments, and can run from the
standalone backend directory. `lexical.py` preserves the research BM25
tokenization and parameters (`k1=0.9`, `b=0.4`).

Keep the snapshot mathematics unchanged. A deliberate future kernel upgrade
must update origin records and pass application/research parity tests. Do not
refactor the frozen research files to maintain this package.

The kernels simulate phase marking and reflection over a compact basis of
subsets. They are classical simulations, with enumeration and simulator work
included in the recorded resources and timings. They are not QPU executions
or evidence of quantum speedup.
