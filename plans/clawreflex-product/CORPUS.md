# Seeded real-source evaluation corpus

`clawreflex/corpus.json` contains 20 independent seeded defects across three pinned
OSS repositories. These are real source files with deliberately introduced bugs;
they are not claims about defects in those upstream releases. The original source
is an evaluation reference and must be withheld from the model.

Fetch the exact releases into a local cache:

```sh
mkdir -p out/clawreflex/corpus-cache
git clone --depth 1 --branch v10.8.0 https://github.com/more-itertools/more-itertools.git out/clawreflex/corpus-cache/more-itertools
git clone --depth 1 --branch 25.0.0 https://github.com/mahmoud/boltons.git out/clawreflex/corpus-cache/boltons
git clone --depth 1 --branch v6.2.1 https://github.com/tkem/cachetools.git out/clawreflex/corpus-cache/cachetools
python -m clawreflex.corpus --cache out/clawreflex/corpus-cache --task boltons-clamp --output /tmp/clawreflex-boltons-clamp
```

The materializer checks commit and target hashes, rejects modified tracked files and
symlinks, copies only tracked files, and refuses an existing output directory. The
task receipt contains no reference solution. It records the import root needed by
the adapter. Tests live in `test_clawreflex_corpus.py` in the prepared repository.

Source provenance and licenses:

- [more-itertools v10.8.0](https://github.com/more-itertools/more-itertools/tree/8c1a6ef241b51ff055e89219f050ccf4f15f37f6), MIT.
- [boltons 25.0.0](https://github.com/mahmoud/boltons/tree/c23dbdadb6fecdf505eb4231559561913b84c13f), BSD-3-Clause.
- [cachetools v6.2.1](https://github.com/tkem/cachetools/tree/ca7508fd56103a1b6d6f17c8e93e36c60b44ca25), MIT.

Full source and upstream license files remain in each fetched checkout; they are
not vendored into the product wheel. The manifest records small mutation contexts
and independent behavioral tests. Retain upstream notices when redistributing sources.

Local corpus validation runs every seeded test in a networkless Bubblewrap sandbox,
checks assertion RED, restores the evaluation reference, and checks GREEN. Results
are in `corpus-validation.json`. This validates the dataset, not repair acceptance.
The >=80% gate requires actual provider-generated repairs, their receipts, scope
checks and the upstream repository's own test suites. No such live acceptance result
has been measured in this session.

The affected upstream modules' baseline suites also ran inside Bubblewrap:
more-itertools recipes: 139 passed, 1 skipped, 9,839 subtests; cachetools keys:
5 passed; boltons mathutils: 11 passed. See `upstream-baseline-tests.json`.
Boltons used `--noconftest` because its release's legacy collection hook is
incompatible with pytest 9; this module uses no shared fixtures. These are
module-suite baselines, not full-repository acceptance runs.
