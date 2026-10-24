# Active output folders

These folders remain at the `results/` root so any currently running Python processes keep writing to their original paths:

- `puccsd3-lbfgsb-1500/` — the first PUCCSD×3 L-BFGS-B run (previously reported PID 2633).
- `puccsd3-extra-lbfgsb-seed20261024/` and `puccsd3-extra-lbfgsb-seed20261024.log` — the additional run (previously reported PID 4187).

The PIDs above are historical user-shared values, not a current process check. In WSL, verify with:

```bash
ps -C python -o pid,etime,%cpu,%mem,cmd
```

After the matching process exits, inspect its log and `summary.json`. If the run completed and its artifacts are consistent, move it into `results/optimizers/`:

```bash
mkdir -p results/optimizers
mv results/puccsd3-lbfgsb-1500 results/optimizers/
mv results/puccsd3-extra-lbfgsb-seed20261024 results/optimizers/
mv results/puccsd3-extra-lbfgsb-seed20261024.log results/optimizers/
```

Do not move a directory while its corresponding process is still running. Update this note and `results/README.md` after the move.