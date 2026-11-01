# Yeh source protection audit — Step 3.3A

Baseline: `ark-yeh` commit `8b1cf75cfac0846e7dc6311b93fd90991e124db8`.

The following protected paths were compared to that commit with both working
tree and index checks: `repository/`, `db/schema/`,
`transaction_scripts/`, `pipeline/`, `data_utils/`, `config.py`,
`main_ass_1.py`, and `requirements.txt`.

Result: all 50 protected tracked files have raw Git blob hashes identical to
the baseline; there is no tracked difference, no staged difference, and no
untracked file in any protected path. `requirements.txt` is Yeh's
byte-identical version.
NiceGUI is declared separately in `requirements-dashboard.txt`.

The only shared Yeh Python file changed is `main_ass_2.py`, as explicitly
authorised for the Part C callback and unified orchestration. Dashboard source,
tests, documentation, and `requirements-dashboard.txt` are Part C additions.
