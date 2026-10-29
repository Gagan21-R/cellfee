"""One-file summary of CELLFEE's recorded QpiAI outputs, for submission:  python -m cellfee.output_report
Reads artifacts/results.json, artifacts/sdk_report.json and artifacts/evidence/ (nothing is re-computed or typed in)
and writes docs/CELLFEE_QpiAI_Output.pdf."""

from __future__ import annotations

import json
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


class PdfPages:
    """Pages rendered as images and joined into one PDF with Pillow (matplotlib's PDF writer needs fontTools,
    whose compiled module some Windows application-control policies block)."""

    def __init__(self, path):
        self.path, self.pages = path, []

    def savefig(self, fig):
        import io
        from PIL import Image
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160)
        self.pages.append(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.pages and not exc[0]:
            self.pages[0].save(self.path, "PDF", resolution=160, save_all=True, append_images=self.pages[1:])

from . import config

OUT = config.ROOT / "docs" / "CELLFEE_QpiAI_Output.pdf"
INK, GREEN, AMBER, RED, PAPER = "#0b0b0b", "#00875f", "#b25e00", "#d62418", "#f2eee3"


def _page(pdf, title: str, lines: list[str], fig=None):
    fig = fig or plt.figure(figsize=(8.27, 11.69))
    fig.patch.set_facecolor("white")
    fig.text(0.07, 0.955, title, fontsize=15, weight="bold", color=INK)
    y = 0.925
    for line in lines:
        for k, part in enumerate(textwrap.wrap(line, 105) or [""]):
            fig.text(0.07 if not line.startswith("  ") else 0.09, y, part, fontsize=8.6, family="monospace" if line.startswith("  ") else None, color=INK)
            y -= 0.0165
        if y < 0.05:
            break
    pdf.savefig(fig)
    plt.close(fig)


def build() -> str:
    R = json.loads(config.RESULTS_JSON.read_text())
    S = json.loads((config.ARTIFACTS / "sdk_report.json").read_text())
    ev = sorted(config.EVIDENCE_DIR.glob("*.json"))
    kinds: dict[str, int] = {}
    for p in ev:
        k = json.loads(p.read_text()).get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    C, A, FP, st = R["comparison"], R["aqsvc"], R["fleet_plan"], S["status"]
    pc = lambda v: f"{v * 100:.2f}%"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        # 1 — summary
        _page(pdf, "CELLFEE · QpiAI outputs (recorded runs)", [
            f"Pipeline run: {R['generated']} · SDK demo: {S['generated']} · QpiAI Quantum SDK {st['qpiai_quantum_version']} · "
            f"QCloud key configured: {st['qcloud_key_configured']} · QpiAI Opt key configured: {st['opt_key_configured']} · devices: {st['kernel_device']}",
            "Everything below is read from artifacts/results.json, artifacts/sdk_report.json and artifacts/evidence/. "
            "Reproduce: cd backend; python -m cellfee.sdk demo (about 5 min) or python -m cellfee.pipeline --retrain (about 70 min).",
            "",
            "WHAT QPIAI COMPUTES",
            f"  QpiAI QCloud   feature-map circuits -> quantum kernel (similarity of two batteries); shot-based fidelity circuits; QAOA",
            f"  QpiAI Opt      every AQSVC SVM trained as an {A['qubo_vars']}-variable QUBO ({A['qubos_solved']} QUBOs this run);",
            f"                 fleet reuse/test/recycle + packs for {FP['batteries']:,} batteries in {FP['batches']} batches (exact MILP); market matching",
            "",
            "VALIDATED RESULT (grouped 5-fold cross-validation by cell, 8,753 real snapshots, 124 LFP cells)",
            f"  AQSVC (quantum: QpiAI kernel + QpiAI Opt QUBOs)   accuracy {pc(C['aqsvc']['accuracy'])}   AUC {C['aqsvc']['auc']:.3f}",
            f"  XGBoost (classical)                               accuracy {pc(C['xgb']['accuracy'])}   AUC {C['xgb']['auc']:.3f}",
            f"  Both together (CELLFEE grade)                     accuracy {pc(C['both']['accuracy'])}   AUC {C['both']['auc']:.3f}",
            f"  Same quantum ensemble, classical solver (C1)      accuracy {pc(C['qsvc']['accuracy'])}",
            f"  Models agree on {pc(R['side_by_side']['agree_rate'])} of snapshots and are right {pc(R['side_by_side']['accuracy_when_agree'])} of those.",
            f"  AQSVC ensemble: {A['bag']} bagged + {A['boost']} boosted QUBO-SVMs on each of {len(A['maps'])} tuned feature maps, stacked "
            f"(plain vote averages {pc(float(np.mean(A['vote_accuracy_by_fold'])))} over the folds).",
            "",
            "FLEET DECISIONS (QpiAI Opt)",
            f"  {FP['opt_milp_batches']} of {FP['batches']} batches solved exactly by QpiAI Opt's MILP; {FP['opt_matches_highs']} of {FP['highs_checked_batches']} "
            f"re-solved by HiGHS give the same objective; {FP['packs']} packs; {FP['forbidden_assignments']} forbidden assignments; all feasible: {FP['all_feasible']}.",
            "",
            f"EVIDENCE: {len(ev)} run records in artifacts/evidence/  ·  " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:10]),
            "",
            "No quantum advantage is claimed: circuits run on QpiAI's local statevector simulator (classical simulation).",
        ])
        # 2 — SDK demo outputs
        k, t, sc, al, qa, mt, vf = (S[x] for x in ("kernel", "train_qubo_svm", "screen", "allocate", "qaoa", "match", "verify"))
        lines = [
            "python -m cellfee.sdk demo: each step is a live QpiAI run with an evidence record (run id in brackets).",
            "",
            f"kernel   [{k['evidence_id']}]  QpiAI SDK statevector overlap {k['exact_statevector']:.4f} · {k['shots']}-shot fidelity circuit on {k['device']}: "
            f"{k['shot_estimate']:.4f} · NumPy twin difference {k['twin_difference']:.1e}",
            f"train    [{t['evidence_id']}]  {t['solver']}: {t['qubo_variables']} binary variables, {t['reads']} reads x {t['sweeps']} sweeps, {t['seconds']} s · "
            f"energy {t['energy_qpiai_opt']:.3f} (built-in annealer {t['energy_builtin_annealer']:.3f}) · held-out accuracy {pc(t['held_out_accuracy_qubo'])} "
            f"(exact classical solution {pc(t['held_out_accuracy_classical_svc'])})",
            f"screen   [{sc['evidence_id']}]  XGBoost {sc['p_xgb']:.3f} · AQSVC {sc['p_aqsvc']:.3f} ({sc['aqsvc_votes']} QUBO-SVMs say fit) · grade {sc['grade']} -> "
            f"{sc['suggested_action']} · circuit {sc['circuit']['qubits']} qubits, depth {sc['circuit']['depth']}",
            f"allocate [{al['evidence_id']}]  batch 1, {al['batteries']} batteries, solved by {al['solved_by']}, objective ₹{al['objective']:.3f}, feasible {al['feasible']}",
        ] + [f"  {r['solver']:<48s} objective {r['objective'] if r['objective'] is None else round(r['objective'], 4)}  time {r['seconds']} s" for r in al["solver_runs"]] + [
            f"qaoa     [{qa['evidence_id']}]  {qa['solver']} · {qa['qubits']} qubits on {qa['device']} · P(optimal split) {qa['optimal_probability']:.3f} "
            f"vs random {qa['random_guess_optimal_probability']:.3f} · approximation ratio {qa['approximation_ratio']:.3f}",
            f"match    [{mt['evidence_id']}]  {mt['solver']}: {len(mt['matches'])} buyer-pack matches from {mt['compatible_pairs']} compatible pairs, total score {mt['total_score']:.4f}",
            "",
            f"verify   [{vf['evidence_id']}]  {vf['passed']} / {vf['total']} reproducibility checks passed",
        ] + [f"  {'PASS' if c['pass'] else 'FAIL'}  {c['check']} — {c['detail']}" for c in vf["checks"]]
        _page(pdf, "CELLFEE SDK · live QpiAI runs and reproducibility", lines)
        # 3 — charts
        fig, axs = plt.subplots(2, 2, figsize=(11.69, 8.27))
        fig.suptitle("CELLFEE · QpiAI outputs at a glance", fontsize=14, weight="bold", x=0.06, ha="left")
        Kq = np.array(R["qml"]["fleet_kernel"])
        im = axs[0, 0].imshow(Kq, cmap="viridis", vmin=0, vmax=1)
        axs[0, 0].set_title(f"Quantum kernel, batch 1 ({len(Kq)} batteries, QpiAI SDK)", fontsize=10)
        fig.colorbar(im, ax=axs[0, 0], fraction=0.046)
        ft = R["qml"]["fidelity_test"]
        axs[0, 1].scatter(ft["exact"], ft["values"], s=14, color=GREEN)
        axs[0, 1].plot([0, 1], [0, 1], color=INK, lw=0.8)
        axs[0, 1].set_title(f"{len(ft['values'])} fidelity circuits, {ft['shots']} shots on {ft['device']}", fontsize=10)
        axs[0, 1].set_xlabel("exact statevector overlap"); axs[0, 1].set_ylabel("shot estimate P(0…0)")
        names = ["rule", "svc_rbf", "xgb_small", "qsvc", "xgb", "aqsvc", "both"]
        labels = ["No ML", "RBF SVM", "XGB small", "C1 quantum,\nclassical solver", "XGBoost", "AQSVC\n(QpiAI)", "Both"]
        vals = [C[n]["accuracy"] * 100 for n in names]
        cols = [INK if n not in ("aqsvc", "both") else GREEN for n in names]
        axs[1, 0].bar(range(len(names)), vals, color=cols)
        axs[1, 0].set_xticks(range(len(names)), labels, fontsize=7)
        axs[1, 0].set_ylim(75, 100); axs[1, 0].set_ylabel("accuracy % (grouped CV)")
        for i, v in enumerate(vals):
            axs[1, 0].text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=7)
        axs[1, 0].set_title("Accuracy on cells never seen in training", fontsize=10)
        folds = R["qml"]["folds"]
        x = np.arange(len(folds))
        axs[1, 1].plot(x + 1, [v * 100 for v in A["vote_accuracy_by_fold"]], "o-", color=AMBER, label="bagging + boosting, plain vote")
        axs[1, 1].plot(x + 1, [f["accuracy"]["aqsvc"] * 100 for f in folds], "o-", color=GREEN, label="AQSVC, stacked")
        axs[1, 1].plot(x + 1, [f["accuracy"]["xgb"] * 100 for f in folds], "s--", color=INK, label="XGBoost")
        axs[1, 1].set_xticks(x + 1); axs[1, 1].set_xlabel("fold"); axs[1, 1].set_ylabel("accuracy %")
        axs[1, 1].legend(fontsize=7); axs[1, 1].set_title("What stacking adds, fold by fold", fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        pdf.savefig(fig)
        plt.close(fig)
        # 4 — sample evidence records
        recent = {}
        for p in reversed(ev):
            r = json.loads(p.read_text())
            recent.setdefault(r.get("kind"), r)
        lines = ["One recent record of each kind, abridged (full JSON in artifacts/evidence/<run_id>.json and on the dashboard's Evidence log)."]
        for kind, r in list(recent.items())[:12]:
            lines += ["", f"{kind}  ·  run {r.get('run_id')}  ·  {r.get('timestamp')}  ·  backend: {r.get('backend', '—')}  ·  device: {r.get('device', '—')}",
                      f"  {str(r.get('summary', ''))[:300]}"]
        _page(pdf, "Evidence records", lines)
    return str(OUT)


if __name__ == "__main__":
    print(build())
