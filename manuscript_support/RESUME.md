# Current continuation point

The manuscript uses completed protected-prefix SciFact and NFCorpus tests and
the earlier 648-query FiQA test. The new full FiQA refinement follow-up has
completed but failed its recall gate; its failure is disclosed separately.
The FiQA 100-query confirmation supplies no headline effectiveness result.

The sealed constrained-oracle study is
`research/runs/resource_study_v1_final/` and is mapped through
`paper_sources.json`. It supplies measured resource data, not new retrieval
tuning. The earlier engineering pilot is preserved separately. See the
resource package README for commands and its explicit simulation limits.

No evaluation should be started by the paper build/export tools. The next full FiQA evaluation requires the user's later start instruction and the frozen experiment's existing recovery/provenance checks. Do not use the obsolete cosine-GAS commands or paused 23-query NFCorpus checkpoint for current manuscript results.

The experiment's continuation state is `research/runs/accuracy_v3_redundancy_continuation_execution.json`; archived reports and checkpoints stay intact. NFCorpus's earlier confirmation failure and explicit continuation exception must remain disclosed.

After a full, sealed 648-query FiQA refinement test exists, follow the **Replace FiQA** procedure in [README.md](README.md). Change the one mapped directory in `paper_sources.json`, then regenerate/verify/build. This automatically updates the selected method, matched controls, paired statistics, numerical tables, configuration note, and generated findings. Do not substitute confirmation metrics or hand-edit a better metric into an old row.

The prior manuscript instructions and source were backed up under `build/paper_revision_before/`.
