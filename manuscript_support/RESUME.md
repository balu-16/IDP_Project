# Current continuation point

The manuscript now uses completed protected-prefix SciFact and NFCorpus tests, and the completed earlier 648-query FiQA test. The separate new FiQA 100-query training confirmation is excluded from the manuscript. Its background continuation stopped after confirmation; it did not start the full FiQA test.

No evaluation should be started by the paper build/export tools. The next full FiQA evaluation requires the user's later start instruction and the frozen experiment's existing recovery/provenance checks. Do not use the obsolete cosine-GAS commands or paused 23-query NFCorpus checkpoint for current manuscript results.

The experiment's continuation state is `research/runs/accuracy_v3_redundancy_continuation_execution.json`; archived reports and checkpoints stay intact. NFCorpus's earlier confirmation failure and explicit continuation exception must remain disclosed.

After a full, sealed 648-query FiQA refinement test exists, follow the **Replace FiQA** procedure in [README.md](README.md). Change the one mapped directory in `paper_sources.json`, then regenerate/verify/build. This automatically updates the selected method, matched controls, paired statistics, numerical tables, configuration note, and generated findings. Do not substitute confirmation metrics or hand-edit a better metric into an old row.

The prior manuscript instructions and source were backed up under `build/paper_revision_before/`.
