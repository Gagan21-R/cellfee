// Knowledge base for the CELLFEE Guide: one entry per dashboard section plus a glossary.
// Every explanation is built from the live pipeline results (R), so numbers always match the page.
// Text format: paragraphs separated by blank lines, "• " starts a bullet, **bold** is emphasis.

const f2 = v => (v == null ? '—' : Number(v).toFixed(2))
const f3 = v => (v == null ? '—' : Number(v).toFixed(3))
const pct = v => (v == null ? '—' : `${Math.round(v * 100)}%`)
import { inr as money } from './usageFormat.js'   // all money is in Indian rupees

function facts(R) {
  const counts = R.fleet.reduce((a, b) => ({ ...a, [b.action]: (a[b.action] || 0) + 1 }), {})
  const grades = R.fleet.reduce((a, b) => ({ ...a, [b.grade]: (a[b.grade] || 0) + 1 }), {})
  const C = R.comparison
  const qa = R.qaoa.runs[0]
  const optRun = R.qaoa.runs.find(r => r.solver.startsWith('QpiAI Opt QAOA'))
  return { counts, grades, C, qa, optRun }
}

export function buildKB(R) {
  const { counts, grades, C, qa, optRun } = facts(R)
  const FP = R.fleet_plan
  const n = v => (v || 0).toLocaleString()
  const fm = R.qml.feature_map
  const p = R.plan
  const A = R.aqsvc
  const S = R.side_by_side
  const LONG = R.assumptions.LONG_LIFE_CYCLES
  const opt = p.solver_runs.find(s => s.solver.includes('QpiAI Opt local MILP'))
  const ann = p.solver_runs.find(s => s.solver.includes('annealer'))

  const E = {}
  const add = (id, title, keywords, text) => { E[id] = { id, title, keywords, text } }

  // ---------------------------------------------------------------- pages
  add('page.overview', 'Overview page', ['overview', 'summary', 'home', 'start', 'project', 'cellfee', 'what is this'],
    `**CELLFEE: give every used battery a second life.**

• **The fleet animation:** each block is one battery, filled by its health and coloured by its decision.
• **Fleet outcomes:** how many batteries were screened, and the reuse / test / recycle split.
• **Two models, side by side:** XGBoost (classical) and AQSVC (quantum) answer the same question for every battery, and how often they agree.
• **How CELLFEE works:** the six-stage path from real lab data to a decision for every battery. Select a stage for its technical detail.`)

  add('page.fleet', 'Fleet & passports tab', ['fleet', 'batteries', 'list', 'board', 'passports', 'passport list'],
    `One tab for the whole fleet and every battery passport: each of the ${R.fleet.length.toLocaleString()} batteries with its **grade**, **measured health**, both models' answers (**XGBoost** and **AQSVC**: the chance it still has at least ${LONG} cycles left), the decision, its truckload batch and pack.

Search, filter by decision or grade, sort, and page through 50 at a time. **View passport** opens the full report over the whole screen: both models, usage baseline, applications with confidence, history, inputs and what really happened. Download it as PDF or JSON (the JSON can be re-uploaded on the Assess & upload tab).`)

  add('page.qml', 'Quantum ML page', ['qml', 'quantum machine learning', 'quantum page', 'qcloud', 'aqsvc page'],
    `This page shows CELLFEE's **quantum model, AQSVC** (annealing-based quantum support vector classifier).

• Each battery's ${R.qml.n_qubits} measurements become rotation angles on a ${R.qml.n_qubits}-qubit **QpiAI circuit**. Comparing two batteries' quantum states gives a **similarity score** (the quantum kernel).
• An SVM uses that kernel to separate "long life ahead" from "near the end". Its training problem is written as a **QUBO** and solved on **QpiAI Opt's annealer**.
• ${A.members} such SVMs are trained on different small groups of batteries. They are combined with four ensemble techniques:
  • **Bagging:** ${A.bag ?? A.members} SVMs per map on random balanced groups.
  • **Boosting:** ${A.boost ?? 0} more per map on groups weighted towards the batteries the first ones got wrong.
  • **Heterogeneous models:** two quantum feature maps, ${(A.maps || []).map(m => `${m.inputs} inputs`).join(' and ')}, each tuned for accuracy on held-out cells.
  • **Stacking:** a logistic-regression meta-learner weighs every SVM's margin into one probability, AQSVC's answer. The plain share of "yes" votes is shown alongside.`)

  add('page.compare', 'XGBoost vs AQSVC page', ['compare', 'comparison', 'classical', 'baseline', 'versus', 'vs', 'better', 'xgboost vs'],
    `This page puts the two models **side by side** and against fair baselines.

• **XGBoost** (classical): ${pct(C.xgb.accuracy)} accurate on cells it never saw.
• **AQSVC** (quantum): ${pct(C.aqsvc.accuracy)}.
• **They agree** on ${pct(S.agree_rate)} of snapshots, and are right ${pct(S.accuracy_when_agree)} of the time when they do. The ${S.disagreements.toLocaleString()} disagreements go to a lab test.

XGBoost is the stronger single model, so we claim no quantum advantage. The two together make safer decisions than either alone.`)

  add('page.opt', 'Decisions (QpiAI Opt) page', ['opt', 'optimisation', 'optimization', 'decisions', 'solver', 'qpiai opt'],
    `This page shows **how the decisions are made** with QpiAI Opt.

The fleet problem (which batteries to reuse, test or recycle, and which reused ones share a pack) is written with QpiAI Opt's modeller. It is solved exactly by **QpiAI Opt's local MILP solver**, and HiGHS confirms the same answer. Every number it uses comes from the two models: the chance of a long life ahead, the measured health and the quantum similarity. The bottom card shows **QAOA** balancing two packs.`)

  add('page.assess', 'Assess & upload tab (typing one battery)', ['assess', 'new battery', 'predict', 'grade a battery', 'try'],
    `Use this page to **screen one battery** by typing its quick test numbers: health now, internal resistance, cycles done, peak temperature and charge time (plus, optionally, how fast capacity and resistance have been changing).

**XGBoost and AQSVC run on it at the same time.** For AQSVC, CELLFEE builds this battery's QpiAI circuit, compares it with the ${A.deployed_support_vectors} support-vector batteries, and ${A.members} SVMs vote. You get both answers side by side, a grade, suitable uses, a service-life range and a CO₂ estimate.`)

  add('page.upload', 'Assess & upload tab', ['upload', 'file', 'csv', 'json', 'test results', 'downloads', 'import', 'assess'],
    `One tab, two ways to screen batteries that are not in the fleet:

• **Upload test results** (default): click **Choose file from Downloads** — Chrome and Edge open your Downloads folder and show every file — or drag a file onto the box. A CSV / JSON test log, a summary, or a **CELLFEE report JSON** you downloaded earlier all work.
• **Recent downloads from CELLFEE:** every file you downloaded here is listed; one click re-screens a test log or report JSON without hunting for it on your device. (A web page cannot look inside your Downloads folder by itself, so CELLFEE remembers its own downloads.)
• **Type one battery's numbers:** the quick form.

Both run XGBoost and AQSVC on every battery at the same time and give the usage baseline and a downloadable PDF / JSON report.`)

  add('page.market', 'Marketplace tab', ['market', 'marketplace', 'buyer', 'seller', 'listing', 'buy', 'sell', 'verified', 'report'],
    `Buy and sell used EV batteries, plus CELLFEE's own packs:

• **Browse batteries:** filter by price, chemistry, capacity, reported SoH, age, city, pack/module, report status and use case. "Best evidence first" ranks by verification, measurements, report recency, SoH and completeness — never SoH alone. Open a listing for its full report and send interest.
• **Sell a battery:** a **quick listing** (drop the report and photos; CELLFEE reads the report and fills the form) or a five-step form with a guide on every step. A **health report is required**: a PDF, a photo or a Word file. Values are read automatically, and you correct them.
• **Marketplace assistant:** ask about the live listings in plain words, e.g. "cheapest LFP in Pune".
• **Checks:** battery-ID mismatch, conflicting SoH, duplicate report or battery ID, re-used report file, outdated report, missing fields — each with its reason. A discrepancy means review, not an accusation.
• **Status:** Report uploaded — not yet verified · Awaiting provider verification · Mismatch · Verification completed (only when a registered testing partner confirms) · Additional testing required · Held.
• **Contact:** the seller sees a buyer's name and message; contact details are shared only when the seller accepts.

Seller report ≠ verified report ≠ safety assessment. The demo testing partners are placeholders for this prototype.`)

  add('page.env', 'Environmental impact page', ['environment', 'environmental', 'co2', 'carbon', 'emissions', 'impact'],
    `This page estimates the **CO₂ difference between reusing a battery and the alternative** (buying a new one, or recycling now).

Every factor is a stated assumption with a low, central and high value, and the result is shown for all three cases. These are estimates under assumptions, not measured savings.`)

  add('page.evidence', 'Evidence log page', ['evidence', 'log', 'runs', 'job', 'proof', 'audit'],
    `This page is the **audit trail**. Every quantum circuit run, every QUBO solved for AQSVC, every optimisation and verification is saved with its device, settings and outputs. Click a row to see the full record, or download it as JSON.`)

  // ---------------------------------------------------------------- overview cards
  add('overview.pipeline', 'How CELLFEE works (architecture)', ['pipeline', 'steps', 'flow', 'architecture', 'how it works', 'diagram'],
    `Read the diagram stage by stage:

• **1 · Battery dataset:** real lab data from MIT, Stanford and Toyota: ${R.data.cells} cells, ${R.data.cycle_records.toLocaleString()} cycles, ${R.data.snapshots.toLocaleString()} screening snapshots.
• **2 · Data preparation:** every cycle validated; each battery's recent history turned into ${R.qml.n_qubits} screening features; scaling fitted on training cells only.
• **3 · XGBoost (classical model):** gradient-boosted trees, ${pct(C.xgb.accuracy)} accurate on unseen cells.
• **4 · AQSVC (quantum model):** QpiAI circuits give the kernel, QpiAI Opt trains ${A.members} SVMs as QUBOs, which are combined by bagging, boosting and stacking: ${pct(C.aqsvc.accuracy)} accurate. It runs on every battery next to XGBoost.
• **5 · QpiAI Opt allocation:** ${FP.batches} truckload batches, each a ${p.qubo.variables}-variable QUBO / exact MILP that picks reuse / test / recycle and builds 4-cell packs.
• **6 · Decisions:** reuse ${n(counts.reuse)} (in ${n(FP.packs)} packs), test ${n(counts.test)}, recycle ${n(counts.recycle)}.`)

  add('overview.screened', 'Batteries screened', ['screened', 'how many batteries', 'fleet size'],
    `**${n(R.fleet.length)}** batteries were screened. Each is a real lab cell captured at a random point in its life, like used batteries arriving at a recycling hub in ${FP.batches} truckloads of about ${FP.batch_size}; no cell appears twice in a truckload.

Every answer for a battery comes from models that **never saw that battery's cell** during training (grouped cross-validation), so the results are honest.`)

  add('overview.actions', 'Reuse · test · recycle', ['reuse', 'test', 'recycle', 'disposition', 'decision counts'],
    `Out of ${n(R.fleet.length)} batteries: **${n(counts.reuse)} reuse**, **${n(counts.test)} full test**, **${n(counts.recycle)} recycle**. The reused batteries form ${n(FP.packs)} matched 4-cell packs.

• **Reuse:** both models expect at least ${LONG} more cycles, so it goes straight into a second-life pack.
• **Test:** the models disagree or are unsure, so a full capacity test is worth it first. The test bench holds ${p.test_capacity} per batch.
• **Recycle:** close to the end of its useful life, or not worth testing given the bench limit.`)

  add('overview.forbidden', 'Forbidden assignments', ['forbidden', 'violations', 'safety', 'constraint', 'zero'],
    `This counts how many times the plan breaks a hard rule, across all ${FP.batches} batches. It should be **0**, and it is **${FP.forbidden_assignments}**.

A "forbidden pair" is two batteries that must never share a pack: their quantum similarity is below ${R.assumptions.KERNEL_FORBID_BELOW}, or their health differs by more than ${pct(R.assumptions.SOH_SPREAD_FORBID)}. Mismatched cells in one pack age unevenly.`)

  add('overview.xgb', 'XGBoost (classical model)', ['xgboost', 'xgb', 'classical model', 'gradient boosting'],
    `**XGBoost** is a widely used classical machine-learning model: hundreds of small decision trees, each correcting the previous ones.

It learned from all ${R.data.snapshots.toLocaleString()} training snapshots and is **${pct(C.xgb.accuracy)} accurate** on cells it never saw (ROC-AUC ${f3(C.xgb.auc)}). It wrongly called ${pct(C.xgb.false_fit_rate)} of short-life batteries "fit".`)

  add('overview.aqsvc', 'AQSVC (quantum model)', ['aqsvc', 'quantum model', 'quantum svm', 'qsvc', 'annealing'],
    `**AQSVC** = annealing-based quantum support vector classifier.

• **Kernel (QpiAI QCloud):** each battery becomes a ${R.qml.n_qubits}-qubit circuit; the overlap of two circuits' states is their similarity.
• **Training (QpiAI Opt):** an SVM's training problem is turned into a ${A.qubo_vars}-variable QUBO and solved by QpiAI Opt's annealer.
• **Ensemble:** ${A.members} SVMs, each trained on ${A.subset} batteries. They are bagged and boosted on two tuned quantum feature maps, then combined by a stacking meta-learner.

Result: **${pct(C.aqsvc.accuracy)} accurate** on unseen cells (ROC-AUC ${f3(C.aqsvc.auc)}).`)

  add('overview.agree', 'When the two models agree', ['agree', 'agreement', 'both models', 'side by side'],
    `XGBoost and AQSVC give the same answer on **${pct(S.agree_rate)}** of snapshots. When they agree they are right **${pct(S.accuracy_when_agree)}** of the time, more often than XGBoost alone (${pct(C.xgb.accuracy)}).

That's why CELLFEE runs both: agreement is a strong signal, and disagreement is a clear reason to test.`)

  add('overview.disagree', 'When the two models disagree', ['disagree', 'disagreement', 'conflict'],
    `On **${S.disagreements.toLocaleString()}** snapshots the models disagree. There, XGBoost is right ${pct(S.accuracy_xgb_when_disagree)} of the time and AQSVC ${pct(S.accuracy_aqsvc_when_disagree)}.

Instead of trusting one model blindly, CELLFEE sends these batteries to a **lab test**: a small cost that avoids building a pack around a battery that won't last.`)

  // ---------------------------------------------------------------- fleet
  add('fleet.table', 'Fleet table', ['table', 'row', 'columns', 'health', 'status', 'board'],
    `Columns: **Health** is measured now (capacity ÷ rating). **XGBoost** and **AQSVC** are each model's chance that the battery still has at least ${LONG} cycles left; ✓ means that model says yes.

Grades now: ${Object.entries(grades).map(([g, n]) => `${g} ${n}`).join(', ')}. Select a row for the full report.`)

  add('passport', 'Battery passport', ['passport', 'drawer', 'details', 'applications', 'duration', 'similar batteries'],
    `The passport is everything CELLFEE knows about one battery:

• **Two models, side by side:** XGBoost's and AQSVC's answers, with AQSVC's stacked probability and how many of its ${A.members} quantum SVMs said yes.
• **Allocation:** the expected value of reuse, test and recycle, and its pack-mates.
• **Inputs:** each value tagged **measured** (latest test) or **from history** (trend over the last 100 cycles).
• **Usage baseline:** state, risk factor and stop period, plus every application it can serve with a confidence %.
• **History:** a timeline from source cell to decision, pack, baseline and run IDs.
• **What really happened:** the true cycles left, held out and never used to decide.

Download it as a plain-language **PDF** or **JSON**.`)

  // ---------------------------------------------------------------- qml
  add('qml.circuit', 'Feature map circuit', ['circuit', 'feature map', 'qubits', 'gates', 'ry', 'rz', 'rzz', 'encoding', 'angles'],
    `This is the **quantum circuit** that represents a battery.

• Each of the ${R.qml.n_qubits} features (${R.data.features.map(f => f.label.toLowerCase()).join(', ')}) gets its own **qubit**.
• The value is scaled to an angle and applied as **RY** and **RZ** rotations.
• **ZZ** gates link neighbouring qubits (entanglement), so the circuit can capture combinations such as "fast fade **and** rising resistance".
• The pattern repeats ${R.qml.layers} times.

The scales (${fm.scales.join(', ')}) and entangling strength (${fm.entangle}) are **learned**.`)

  add('qml.training', 'Kernel-target alignment training', ['training', 'alignment', 'kernel target alignment', 'learn', 'optimiser', 'fold'],
    `Before the SVMs are trained, the circuit itself is trained. **Kernel-target alignment** measures how well the circuit's similarity agrees with the labels: batteries with the same future should look alike. An optimiser tunes the circuit's scales and entangling strength to raise it.

Fold 1 rose from ${f3(R.qml.folds[0].alignment_untrained)} untrained to ${f3(R.qml.folds[0].alignment_trained)} trained.`)

  add('qml.kernel', 'Quantum kernel heatmap', ['heatmap', 'kernel', 'similarity', 'matrix', 'fleet kernel'],
    `Each square is the **quantum similarity** between two fleet batteries, from 0 (very different) to 1 (identical), from QpiAI SDK statevectors.

The same matrix is the optimiser's **pack compatibility** cost: similar batteries are cheap to put together, and very low similarity (< ${R.assumptions.KERNEL_FORBID_BELOW}) is forbidden.`)

  add('qml.aqsvc', 'Training SVMs as QUBOs', ['qubo svm', 'aqsvc training', 'alpha', 'support vectors', 'annealer', 'willsch'],
    `An SVM decides by weighting a few "support vector" batteries. Normally the weights α come from a classical solver. In AQSVC:

• each weight is written with ${A.bits} binary bits (α = 0…${2 ** A.bits - 1}), so ${A.subset} batteries make **${A.qubo_vars} binary variables**;
• the SVM training objective becomes a **QUBO**: ${A.formulation};
• **QpiAI Opt's local annealer** solves it (${A.reads} reads × ${A.sweeps} sweeps, inside the free local budget).

This run solved **${A.qubos_solved} QUBOs** (about ${f2(A.mean_seconds_per_qubo)} s each), with ${f2(A.mean_support_vectors)} support vectors per SVM on average. The deployed model needs ${A.deployed_support_vectors} support-vector circuits, computed on the QpiAI SDK.`)

  add('qml.fidelity', 'Shot-based fidelity test', ['fidelity', 'shots', 'run circuits', 'compute uncompute', 'button', 'hardware', 'indus'],
    `This checks the kernel the way a **real quantum computer** would compute it.

For two batteries the circuit runs battery A forward and battery B in reverse, then measures all qubits ${R.qml.fidelity_test.shots} times. The fraction of all-zero results estimates their similarity. Here ${R.qml.fidelity_test.pairs.length} pairs ran on ${R.qml.fidelity_test.device}, with an average gap of ${f3(R.qml.fidelity_test.mean_abs_error)} from the exact value: just shot noise.

**"Run 6 new kernel circuits"** runs fresh circuits now. With QCloud credits the same circuits can run on QpiAI's cloud simulators or the QpiAI-Indus-1 quantum computer.`)

  // ---------------------------------------------------------------- compare
  add('compare.table', 'Comparison table', ['comparison table', 'columns', 'accuracy', 'auc', 'brier', 'false fit', 'unfit'],
    `Seven rows, all answering the same question:

• **A · Health threshold:** no ML, just "fit if health ≥ a learned threshold".
• **B1 · XGBoost, same data budget:** XGBoost trained on only the batteries AQSVC saw.
• **B2 · Classical SVM ensemble:** same subsets, classical RBF kernel.
• **B · XGBoost:** the classical production model, trained on everything.
• **C1 · Quantum-kernel SVM, classical solver:** isolates what the annealer changes.
• **C · AQSVC:** the quantum production model.
• **B + C · Both together:** CELLFEE's combined answer.

**Accuracy / AUC / Brier / false "fit"** come from grouped cross-validation. **Realised value / unfit reused / good cells recycled** score the fleet plan built from each row's answers against what really happened.`)

  add('compare.value', 'Accuracy and value charts', ['value chart', 'value bars', 'plan value', 'accuracy chart'],
    `Left: accuracy on unseen cells. Right: what each plan is worth when scored against the real outcome:

${['rule', 'xgb', 'aqsvc', 'both'].map(k => `• ${C[k].label}: ${pct(C[k].accuracy)} accurate, plan worth ${money(C[k].realized_value)}`).join('\n')}`)

  add('compare.agree', 'Side-by-side statistics', ['agree rate', 'right when they agree', 'disagreements', 'side by side'],
    `Both models answered all ${R.data.snapshots.toLocaleString()} snapshots:

• they agree on **${pct(S.agree_rate)}**, and are right **${pct(S.accuracy_when_agree)}** of the time when they do;
• on the **${S.disagreements.toLocaleString()}** disagreements, XGBoost is right ${pct(S.accuracy_xgb_when_disagree)} and AQSVC ${pct(S.accuracy_aqsvc_when_disagree)} of the time.

So disagreement is a reliable warning sign, and CELLFEE turns it into "test first".`)

  // ---------------------------------------------------------------- opt
  add('opt.fleet', 'Fleet decided in batches', ['batches', 'truckload', 'batch', '5000', 'whole fleet'],
    `The ${n(FP.batteries)} batteries arrive in **${FP.batches} truckloads** of about ${FP.batch_size}, and no lab cell appears twice in a truckload. Each truckload is one QpiAI Opt problem: reuse / test / recycle plus packs.

• **QpiAI Opt exact MILP** decided all ${FP.opt_milp_batches} batches; HiGHS re-solved the first ${FP.highs_checked_batches} and matched ${FP.opt_matches_highs} exactly.
• **Packs built:** ${n(FP.packs)}. **Forbidden assignments:** ${FP.forbidden_assignments}. ${FP.all_feasible ? 'Every batch passes the independent constraint check.' : 'A batch FAILED the constraint check.'}
• **Expected value of the whole plan:** ${money(FP.objective)}.

A single problem over all ${n(FP.batteries)} batteries would have millions of pack-pairing variables, beyond any exact solver, and a hub decides one truckload at a time anyway.`)

  add('opt.graph', 'How batch 1 was decided (graph)', ['graph', 'nodes', 'edges', 'how batch', 'compatible pairs'],
    `Each dot is one battery from batch 1, coloured by its decision. A line joins two reuse candidates that **may** share a pack; **red** lines are forbidden pairs (quantum similarity below ${R.assumptions.KERNEL_FORBID_BELOW} or a health gap above ${pct(R.assumptions.SOH_SPREAD_FORBID)}). The dots then move into QpiAI Opt's real plan: packs (with their total capacity in Ah), test and recycle. Batteries the hard rule blocks from reuse have no lines.

The allocation solver (an exact MILP) does not produce an energy trace, so none is drawn here; the curve on the QAOA card is QAOA's real optimiser trace.`)

  add('opt.qubo', 'QUBO variables', ['qubo', 'variables', 'binary', 'terms'],
    `**QUBO** (Quadratic Unconstrained Binary Optimisation) is the format quantum and quantum-inspired optimisers use: every decision is a 0/1 variable.

QpiAI Opt compiled the fleet problem into **${p.qubo.variables} binary variables** and **${p.qubo.terms} terms**.`)

  add('opt.forbidden', 'Forbidden pairs (learned)', ['forbidden pairs', 'learned pairs', 'incompatible'],
    `**${p.forbidden_pairs}** battery pairs are banned from sharing a pack: quantum similarity < ${R.assumptions.KERNEL_FORBID_BELOW}, or a health gap > ${pct(R.assumptions.SOH_SPREAD_FORBID)}. The optimiser enforces them as hard constraints.`)

  add('opt.check', 'Constraint check', ['constraint check', 'pass', 'feasible', 'violations'],
    `After solving, CELLFEE re-checks every rule: one action per battery, packs of exactly ${R.assumptions.PACK_SIZE}, reused cells in exactly one pack, no forbidden pairs, and test-bench capacity. Result: **${p.constraint_check.feasible ? 'Pass' : 'Fail'}** with ${p.constraint_check.violations.length} violations.`)

  add('opt.objective', 'Objective (expected ₹)', ['objective', 'expected value', 'solved by'],
    `**${money(p.objective)}** is the plan's **expected** value, computed from the two models' answers before anyone knows the real outcome. Solved by **${p.solved_by}**.`)

  add('opt.model', 'The optimisation model', ['model', 'formulation', 'constraints', 'objective function', 'math'],
    `The exact model given to QpiAI Opt:

• **Variables:** reuse (r), test (t) or recycle (c) per battery; y = battery in pack p; u = pack p built.
• **Rules:** one action per battery; a reused battery in exactly one pack; packs of ${R.assumptions.PACK_SIZE}; forbidden pairs never together; at most ${p.test_capacity} tests per batch.
• **Goal:** maximise expected value minus a mismatch penalty.

The chance of a long life ahead is the average of XGBoost and AQSVC; the energy value comes from the measured health; the mismatch uses the quantum similarity and the health gap.`)

  add('opt.solvers', 'Solver runs & packs', ['solver runs', 'milp', 'highs', 'annealer', 'packs', 'exact'],
    `The same problem was solved several ways:

• **QpiAI Opt local MILP (exact):** objective ${money(opt?.objective)}, proven optimal${opt?.matches_highs ? ', and it **matches HiGHS exactly**' : ''}. This one makes the decision.
• **HiGHS:** an independent exact solver, used as a cross-check.
• **QpiAI Opt QUBO annealer:** within the free local budget it ${ann && ann.feasible === false ? "couldn't satisfy every constraint of this large, constrained problem; we report that honestly (the smaller, unconstrained AQSVC QUBOs are solved well by the same annealer)" : 'returned a feasible plan'}.

**Packs:** ${n(FP.packs)} across the fleet; batch 1 built ${p.packs.length}.`)

  add('opt.qaoa', 'QAOA pack balancing', ['qaoa', 'quantum optimisation', 'quantum optimization', 'xy mixer', 'cvar', 'pack balance', 'split'],
    `**QAOA** is a quantum circuit with adjustable angles, tuned until its measurements favour good answers.

Here it splits ${R.qaoa.cell_ids.length} reuse cells into two packs of ${R.qaoa.n_qubits / 2} with the least mismatch:

• An **XY mixer** keeps every sample a valid 4+4 split.
• **CVaR** focuses training on the best samples.
• **Best sampled split:** ${f3(qa.best_objective)}, vs the exact optimum ${f3(R.qaoa.exact.objective)}.
• **P(optimal):** ${f3(qa.optimal_probability)} vs ${f3(qa.random_guess_optimal_probability)} for random guessing.
${optRun ? `• **QpiAI Opt's own QAOA:** ${optRun.error ? 'errored' : `objective ${f3(optRun.objective)}${optRun.feasible ? ', a valid split' : ''}`}.` : ''}`)

  // ---------------------------------------------------------------- assess
  add('assess.form', 'Assessment inputs', ['inputs', 'resistance', 'cycle count', 'temperature', 'charge time', 'form', 'fade'],
    `What to enter (from a battery tester or BMS log):

• **Health now:** measured capacity ÷ rated capacity (e.g. 0.93).
• **Internal resistance** (mΩ), **cycles done**, **peak temperature** per cycle and **charge time** per cycle.
• **Optional history:** capacity lost and resistance rise per 100 cycles. Leave them blank and CELLFEE uses a typical value and tells you so.
• **Transport distance:** only for the CO₂ estimate.

Have a full test log? Switch to **Upload test results** on the same tab; it computes everything from the file.`)

  add('assess.result', 'Assessment result', ['result', 'output', 'grade', 'nearest', 'circuit depth', 'disclaimer'],
    `The result shows:

• **Both models side by side:** XGBoost's chance and AQSVC's stacked probability (with its SVMs' vote), each with how long it took. They ran at the same time.
• **Grade and verdict:** A/B reuse, T test first, C recycle.
• **Quantum circuit:** this battery's ${R.qml.n_qubits}-qubit QpiAI circuit (depth and gate count).
• **Applications, duration, CO₂** and the **most similar fleet batteries**.

Download it as a plain-language PDF or JSON. It's preliminary decision support only, not a safety certification.`)

  add('upload.how', 'How uploading works', ['how upload', 'file format', 'columns', 'cycle log', 'summary file', 'sample'],
    `Two kinds of file work:

• **A cycle log** (what a battery tester exports): one row per cycle with battery id, cycle, discharge capacity, internal resistance, peak temperature and charge time. CELLFEE uses the last 100 or so valid cycles.
• **A summary:** one row per battery with the features already worked out.

Column names are matched flexibly and units such as mAh, mΩ and seconds are recognised. Try **Download a sample test log** (real cycler data from three lab cells) and upload it. The file is processed by your local CELLFEE server and not stored.`)

  add('upload.recent', 'Recent uploads', ['recent', 'history', 'previous upload', 'reopen'],
    `Your last 5 uploads are remembered **in this browser only** (nothing is sent anywhere). Click one to reopen its result without uploading again, or clear the list.

Websites can't look inside your Downloads folder by themselves; the file picker (which opens in Downloads on Chrome and Edge) or drag-and-drop is how you hand CELLFEE a file.`)

  // ---------------------------------------------------------------- buy & sell marketplace
  add('market.browse', 'Browse batteries', ['browse', 'filter', 'filters', 'search battery', 'find a battery', 'best evidence', 'ranking'],
    `Every listed battery, with its photos, reported health and report status.

• **Filters:** price, chemistry, capacity, reported SoH, age, city, complete pack or module, report status and use case.
• **Sort "Best evidence first":** 40% verification, 20% measurements present, 15% report recency, 15% reported SoH, 10% listing completeness. A battery never ranks high on SoH alone.
• **View details** opens the full listing: the original report, the automatic checks, possible uses, and a form to send interest.
• Listings tagged **Demo listing** are fictional sample data.`)
  add('market.status', 'Report status labels', ['status', 'awaiting provider', 'not yet verified', 'verification completed', 'additional testing', 'mismatch', 'held', 'verified mean'],
    `What each label means:

• **Verification completed:** a registered testing partner re-tested the battery and confirmed the report ID and SoH (within 1 point).
• **Awaiting provider verification:** the report names a registered partner; their confirmation is pending.
• **Report uploaded, not yet verified:** the report is from a lab that is not a registered partner.
• **Additional testing required:** the report is older than the policy allows.
• **Mismatch / Held:** serial numbers or SoH disagree, or the report is reused on another listing. These are hidden from buyers until resolved.

None of them is a safety certificate.`)
  add('market.sell', 'Sell a battery', ['sell', 'selling', 'list my battery', 'how to sell', 'seller', 'step by step'],
    `Two ways to list a battery:

• **⚡ Quick listing (recommended):** drop the health report (PDF, Word or a photo of it) and a few photos. CELLFEE reads the report and fills in the make, model, chemistry, serial, capacity, SoH, lab and test date. You check them, add a price and your contact, preview and submit.
• **Step-by-step form:** five steps with a guide on each: details, report, price, photos, preview.

A report is required. Automatic checks run before the listing goes live, and your contact stays private until you accept a buyer. No files? Download the sample report and photos from the Sell tab.`)
  add('market.quick', 'Quick listing', ['quick listing', 'quick', 'drop', 'pdf', 'photos', 'auto fill', 'autofill', 'read my files'],
    `Drop the report and up to 8 photos together. A PDF or Word file becomes the report; images become the photos (first = exterior, second = label).

CELLFEE then reads "Label: value" lines and common phrases from the report: lab, report ID, test date, serial, manufacturer, model, vehicle, age, city, pack/module, chemistry, capacity, voltage, SoH and internal resistance. Each value shows the text it came from, and fields read from the report are highlighted in green. Fields still needed are highlighted in orange. Nothing is guessed: anything not found stays empty for you to fill.`)
  add('market.mine', 'My listings & interests', ['my listings', 'my interests', 'accept', 'decline', 'mark sold', 'withdraw', 'demo accounts', 'persona'],
    `Your side of the marketplace, kept in this browser (the server stores only hashed keys).

• **As a seller:** see each listing's status and checks, accept or decline buyers (accepting shares both contacts), mark it sold, or withdraw it.
• **As a buyer:** see each request's status; once accepted, you see the seller's contact.
• **Open demo accounts** loads two fictional personas: a seller with four listings and a buyer with five requests.`)
  add('market.partners', 'Testing partners (demo)', ['testing partner', 'partners', 'partner code', 're-test', 'retest', 'confirm report'],
    `Only a registered testing partner can move a listing to **Verification completed**. They confirm the report ID and the SoH they measured. If the SoH differs by more than 1 point, the result is a mismatch.

The queue lists public listings whose report names a registered partner and is waiting for confirmation. **Re-test this one** fills in the form. Demo partner codes are shown because this is a prototype; in production a partner would confirm through an authenticated API.`)
  add('market.assistant', 'Marketplace assistant', ['assistant', 'chat', 'chatbot', 'ask the marketplace'],
    `A chat box that answers from the **live listings**. Examples: "cheapest LFP battery in Pune", "verified batteries under 1 lakh", "packs above 85% SoH", "how many listings", "how do I sell", "what does awaiting provider mean". Matching listings come with a **View** button. It is a rule-based assistant over this marketplace's data, not a general AI.`)

  // ---------------------------------------------------------------- CELLFEE packs & matching
  add('market.listings', 'Listings', ['listings', 'sellers', 'packs for sale', 'price', 'verified'],
    `Batteries offered for a second life. **PACK-** listings are the packs CELLFEE built, priced from their measured energy. **LST-** listings are example seller listings. Each shows energy (Wh), the weakest cell's health, price and whether its evidence is verified.`)

  add('market.buyer', 'Post a buyer requirement', ['post', 'add buyer', 'requirement', 're-match', 'budget'],
    `Describe what you need (application, minimum energy, budget, location, whether a test report is required) and click **Add & re-match**. CELLFEE re-runs the matching with your request included, solved with QpiAI Opt.`)

  add('market.matches', 'Matches', ['matches', 'score', 'assignment', 'one to one'],
    `The final pairing: each buyer gets at most one listing and each listing at most one buyer, maximising the total score. Solved by **${R.market.solver}**.

The score weighs energy fit (45%), price headroom (30%), distance (15%) and verification (10%), and is applied only to pairs that passed every hard rule.`)

  add('market.screen', 'Compatibility screen', ['compatibility', 'screen', 'blocked', 'why not', 'grid'],
    `Every buyer × listing combination. A green score means compatible; ✕ shows the first rule that blocked it (health too low, too little life left, not enough energy, over budget, missing report). Hover a cell for all the reasons.`)

  // ---------------------------------------------------------------- environment
  add('env.inputs', 'Scenario inputs & assumptions', ['assumptions', 'factors', 'baseline', 'inputs'],
    `Set the battery's health, size, transport distance and the **baseline** (buy a new battery, or recycle now). The table lists every emission factor as low / central / high: stated assumptions from typical literature ranges, not measurements.`)

  add('env.result', 'Net emissions avoided', ['net emissions', 'kg co2', 'low central high', 'result'],
    `The estimated CO₂e avoided by reusing instead of the baseline, for the low, central and high assumption sets: avoided manufacturing minus the refurbishment, extra-losses and transport burden. Manufacturing is credited once and recycling is delayed, not avoided, so nothing is double counted.`)

  add('env.totals', 'Totals: fleet plan and marketplace', ['total', 'totals', 'fleet impact', 'marketplace impact', 'equivalent', 'trees', 'car km', 'how much co2'],
    `The same estimate added up over many batteries:

• **Fleet plan, reused:** the cells QpiAI Opt sent straight to reuse.
• **Fleet plan, expected after testing:** cells sent to a test, each counted by the models' chance that the test confirms it.
• **Marketplace:** every listed battery, as if each found a second-life buyer instead of a new battery being made. Sold listings are shown separately.

**Equivalents** (petrol-car km, tree-years, grid kWh, LPG cylinders) restate the central case in everyday units, using stated factors. All of these are estimates, not measured savings. The marketplace uses sellers' reported SoH, and the demo listings are fictional.`)

  // ---------------------------------------------------------------- evidence
  add('evidence.sdk', 'QpiAI Quantum SDK', ['sdk', 'version', 'kernel device'],
    `The QpiAI Quantum SDK version that built and ran the circuits (${R.sponsor_status.qpiai_quantum_version}), and where kernel circuits run: **${R.sponsor_status.kernel_device}**, QpiAI's local statevector simulator. It needs no cloud credits, as the hackathon mentors advised.`)

  add('evidence.qaoa', 'QAOA device', ['qaoa device'],
    `Where the QAOA circuits are sampled: **${R.sponsor_status.qaoa_device}**.`)

  add('evidence.opt', 'Opt solver', ['opt solver', 'key configured'],
    `Which optimiser is active: **${R.sponsor_status.opt_solver}**, using your QpiAI Opt key. It trains AQSVC (${A.qubos_solved} QUBOs this run) and makes the fleet and marketplace decisions.`)

  add('evidence.runs', 'Runs recorded', ['runs recorded', 'count'],
    `How many run records exist in artifacts/evidence/. Each pipeline run adds records for the AQSVC training, the twin check, kernel circuits, allocations, QAOA and market matching.`)

  add('evidence.log', 'Run records', ['records', 'json', 'run id', 'audit trail'],
    `One row per recorded run. Click a row to see the full saved JSON, including settings, outputs and any QpiAI job IDs, and download it.`)

  // ---------------------------------------------------------------- architecture stages (click a stage)
  add('arch.1', 'Stage 1 · Battery dataset', ['stage 1', 'dataset stage', 'input data'],
    `**Classical · Operational.** Source: ${R.data.source}.

• **${R.data.cells} cells**, **${R.data.cycle_records.toLocaleString()} cycle records**, ${R.data.policies} different fast-charge protocols, all cycled until they fell to 80% capacity.
• A **snapshot** is one battery at one moment, described only by its recent test history: **${R.data.snapshots.toLocaleString()} snapshots** (${pct(R.data.fit_share)} fit).
• **Label:** ${R.data.target}. It comes from the battery's real future, so it's used only to train and evaluate, never as an input.`)
  add('arch.2', 'Stage 2 · Data preparation', ['stage 2', 'preprocessing', 'validation', 'cleaning', 'scaling'],
    `**Classical · Operational.** What the code does (backend/cellfee/data.py):

• **Validation:** a cycle counts only if capacity, resistance, temperature and charge time are in physical ranges; ${R.data.excluded.invalid_cycle_records} cycle records failed.
• **Features (${R.qml.n_qubits}):** ${R.data.features.map(f => f.label).join(', ')}. Trends come from the last 100 cycles.
• **Scaling:** each feature mapped to a rotation angle in [0, π] using the **training cells only**.
• **Splitting:** 5-fold cross-validation **grouped by cell**, so no battery is in both training and testing.`)
  add('arch.3', 'Stage 3 · XGBoost (classical model)', ['stage 3', 'classical ml', 'xgboost stage', 'scikit-learn'],
    `**Classical · Operational.** XGBoost, 300 trees of depth 4, trained on every training snapshot:

• accuracy **${pct(C.xgb.accuracy)}**, ROC-AUC ${f3(C.xgb.auc)}, false "fit" rate ${pct(C.xgb.false_fit_rate)}, all measured on unseen cells;
• it runs on every battery, at the same time as AQSVC, for the fleet, the Assess page and uploads.`)
  add('arch.4', 'Stage 4 · AQSVC (quantum model)', ['stage 4', 'quantum experiment', 'circuit', 'qcloud stage', 'encoding'],
    `**QpiAI QCloud + QpiAI Opt · Simulator.**

• **Kernel:** ${R.qml.n_qubits} features → ${R.qml.n_qubits} qubits (RY, RZ, ring RZZ, ${R.qml.layers} layers), built with qpiai-quantum ${R.sponsor_status.qpiai_quantum_version}; trained by kernel-target alignment.
• **Training:** ${A.members} SVMs per model, each a ${A.qubo_vars}-variable QUBO solved on QpiAI Opt's annealer (${A.qubos_solved} QUBOs this run).
• **Measurement check:** ${R.qml.fidelity_test.pairs.length} compute-uncompute circuits at ${R.qml.fidelity_test.shots} shots on ${R.qml.fidelity_test.device}, mean gap ${f3(R.qml.fidelity_test.mean_abs_error)} from exact.
• **Result:** accuracy **${pct(C.aqsvc.accuracy)}**, ROC-AUC ${f3(C.aqsvc.auc)} on unseen cells.

No QPU hardware run is claimed.`)
  add('arch.5', 'Stage 5 · QpiAI Opt allocation', ['stage 5', 'optimisation stage', 'optimization stage', 'qubo formulation', 'solver'],
    `**QpiAI Opt · Operational.** Built with the QpiAI Opt modeller (backend/cellfee/allocation.py):

• **${p.qubo.variables} QUBO binaries**, ${p.qubo.terms} terms; packs of ${R.assumptions.PACK_SIZE}; ${p.forbidden_pairs} forbidden pairs; at most ${p.test_capacity} tests.
• **Inputs from the models:** chance of a long life (average of XGBoost and AQSVC), measured health, quantum similarity.
• **Solver:** ${p.solved_by}, objective ${money(p.objective)}, ${p.constraint_check.feasible ? 'all constraints verified' : 'constraint check FAILED'}.`)
  add('arch.6', 'Stage 6 · Battery decisions', ['stage 6', 'results stage', 'decisions stage', 'outputs'],
    `**Operational.** Outputs:

• reuse ${n(counts.reuse)}, test ${n(counts.test)}, recycle ${n(counts.recycle)};
• ${n(FP.packs)} packs of ${R.assumptions.PACK_SIZE} across ${FP.batches} batches;
• per battery: both models' answers, grade, the reason in plain words, and a downloadable passport.

Preliminary decision support, not safety certification.`)

  // ---------------------------------------------------------------- glossary (chat only)
  add('g.soh', 'State of Health (health)', ['soh', 'state of health', 'health', 'capacity'],
    `**Health (SOH)** = the battery's current capacity ÷ its rated capacity (1.1 Ah for these LFP cells). 100% = like new. These cells were run until 80%, the usual end of an EV battery's first life.`)
  add('g.long', 'What "fit for second life" means', ['fit', 'long life', 'second life', 'cycles left', '300 cycles', 'label'],
    `A battery is **fit for second life** if it still has **at least ${LONG} full cycles** left before it falls to 80% of its rated capacity. Both models answer that question with a probability.`)
  add('g.kernel', 'Quantum kernel', ['quantum kernel', 'kernel', 'fidelity kernel', 'overlap'],
    `A **quantum kernel** measures similarity by putting each battery into a quantum state (via the circuit) and measuring how much two states overlap: k = |⟨ψ(a)|ψ(b)⟩|². 1 means identical. AQSVC uses it to classify, and the optimiser uses it to build packs.`)
  add('g.svm', 'Support vector machine (SVM)', ['svm', 'support vector', 'classifier'],
    `An **SVM** separates two groups by leaning on a few key examples, the support vectors, weighted by α. AQSVC finds those weights by solving a QUBO on QpiAI Opt instead of a classical solver.`)
  add('g.qubit', 'Qubit', ['qubit', 'qubits', 'quantum bit'],
    `A **qubit** is the quantum version of a bit. Rotations (RY, RZ) set its state and entangling gates (ZZ) link qubits. CELLFEE uses ${R.qml.n_qubits} qubits per battery, and ${R.qaoa.n_qubits} for QAOA.`)
  add('g.qpiai', 'QpiAI QCloud & QpiAI Opt', ['qpiai', 'sponsor', 'qcloud', 'qpiai opt', 'indus'],
    `The hackathon sponsor's two tools:

• **QpiAI QCloud / Quantum SDK** builds and runs the circuits (kernel, fidelity tests, QAOA), here on QpiAI's local simulator.
• **QpiAI Opt** trains AQSVC (QUBOs), and makes the fleet and marketplace decisions.`)
  add('g.reuse_rule', 'Why a battery is reused, tested or recycled', ['why', 'why reused', 'why tested', 'why recycled', 'decide', 'rule'],
    `For each battery, P = the average of XGBoost's and AQSVC's chance of a long life ahead. Then:

• **Reuse** = P × energy value − (1 − P) × rework cost.
• **Test** = P × value + (1 − P) × recycling value − test cost.
• **Recycle** = recycling value.

The optimiser picks the best combination **for the whole fleet at once**, respecting test-bench capacity and pack compatibility.`)
  add('g.grades', 'Grades A / B / T / C', ['grade', 'grades', 'a b c', 'grade t'],
    `Grades come from the two models together:

• **A:** both say yes, combined chance ≥ ${pct(R.assumptions.GRADE_A_P)}.
• **B:** both say yes, combined chance ≥ ${pct(R.assumptions.GRADE_B_P)}.
• **T:** they disagree or are unsure, so a full test is needed.
• **C:** both say no, combined chance ≤ ${pct(R.assumptions.GRADE_C_P)}: recycling route.`)
  add('g.data', 'The data', ['data', 'dataset', 'severson', 'mit', 'stanford', 'toyota', 'where data', 'real data'],
    `Real laboratory data: ${R.data.source}. ${R.data.cells} cells, ${R.data.cycle_records.toLocaleString()} cycles, turned into ${R.data.snapshots.toLocaleString()} screening snapshots. It's one of the most cited battery-ageing datasets.`)
  add('qml.ensemble', 'AQSVC ensemble', ['ensemble', 'bagging', 'boosting', 'stacking', 'voting', 'meta-learner', 'heterogeneous', 'accuracy improve', 'how accurate'],
    `How AQSVC gets from one small quantum SVM to **${pct(C.aqsvc.accuracy)}**, using four ensemble techniques:

• **Better quantum feature maps:** inputs are rank-encoded to rotation angles. One map adds an 8th input: the cycles left until 80% health at the recent fade rate (computed from two existing features). The scales are tuned for accuracy on held-out training cells.
• **Bagging:** ${A.bag ?? '—'} SVMs per map, each trained as a QUBO on a random balanced group of ${A.subset} batteries.
• **Boosting:** ${A.boost ?? '—'} more per map, on groups drawn towards the batteries the first round got wrong or nearly wrong.
• **Heterogeneous models + stacking:** both maps' SVM margins go into a logistic-regression meta-learner, fitted on out-of-bag margins. Its probability is AQSVC's answer. The plain vote is shown alongside.

All accuracies are on cells the models never saw. The **C1** baseline runs the same maps and ensemble with a classical solver, which isolates the annealer's effect.`)
  add('g.advantage', 'Is there a quantum advantage?', ['advantage', 'better than classical', 'faster', 'speedup', 'real quantum computer'],
    `We **don't claim** one. ${C.aqsvc.accuracy >= C.xgb.accuracy ? `AQSVC now matches XGBoost (${pct(C.aqsvc.accuracy)} vs ${pct(C.xgb.accuracy)})` : `XGBoost is still slightly more accurate (${(C.xgb.accuracy * 100).toFixed(1)}% vs ${(C.aqsvc.accuracy * 100).toFixed(1)}%)`}, and XGBoost is far faster to train. The circuits run on a simulator, which is classical computation. AQSVC got close by ensembling (bagging, boosting, two tuned feature maps, stacking), not by a quantum speed-up. Its value is as a working, independent quantum second opinion: when both models agree, they are right ${pct(S.accuracy_when_agree)} of the time.`)
  add('g.safety', 'Is a reused battery safe?', ['safe', 'safety', 'certify', 'certified', 'install'],
    `CELLFEE's grades and matches are **preliminary decision support, not safety certification**. Any real reuse needs qualified inspection, BMS compatibility checks, electrical and thermal integration review, and the applicable safety standards.`)

  // ---------------------------------------------------------------- usage baselines (risk, stop period, confidence)
  const UB = R.usage
  if (UB) {
    const V = UB.validation
    const cov = Object.entries(V.stop_period_models).map(([f, v]) => `${Math.round(+f * 100)}% floor: ${pct(v.coverage_p10_p90)}`).join(', ')
    add('usage.pack', 'Usage baseline per pack', ['usage baseline', 'pack baseline', 'limiter', 'weakest member', 'stop period', 'stop use'],
      `After QpiAI Opt builds a pack, its **weakest member governs**: the pack's stop period and each application's confidence are the **minimum over its 4 batteries**, and that battery is named as the **limiter**.

• **States:** Safe, Approaching limit (cautious stop period within ${UB.baselines.states.approaching_margin_cycles} cycles), Stop use.
• **Across the fleet:** ${Object.entries(UB.counts).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(', ')}.
• The limits are **configured baselines** (registry/applications.json, registry/baselines.json), not facts: ${UB.label}

${UB.note}`)
    add('usage.stop', 'Stop period', ['stop period', 'stop by', 'how long', 'remaining', 'p10', 'p90', 'months'],
      `The **stop period** is how many more full cycles a battery can be used before its health falls below the application's **health floor**.

It comes from an XGBoost quantile model trained on the real cycling data: P10 (cautious, "stop by"), P50 (typical) and P90, capped at the configured cycles in service. Out-of-fold check, how often the true value fell inside P10–P90: ${cov}. Months use each application's cycles per year.`)
    add('usage.risk', 'Risk factor', ['risk', 'risk factor', 'risk level', 'fire', 'danger'],
      `**Risk factor** = a weighted mean of five 0–1 parts: health margin to 80%, capacity fade rate, resistance rise, peak temperature, and model doubt (1 when XGBoost and AQSVC disagree). Levels: Low, Elevated, High.

On the training data, the share that fell to 80% health within 100 cycles was: ${Object.entries(V.risk_levels).map(([k, v]) => `${k} ${v.reached_80pct_within_100_cycles == null ? '—' : pct(v.reached_80pct_within_100_cycles)}`).join(', ')}. The level caps which safety tier of application a battery may serve. It is not a fire-risk measurement: the dataset records no fires.`)
    add('usage.confidence', 'Application confidence', ['confidence', 'can be used for', 'application', 'applications', 'suitability'],
      `"Can be used for X with confidence Y%" = the probability, from an XGBoost classifier trained for X's requirement, that the battery stays above X's health floor for X's required cycles. Measured requirements (chemistry, health, capacity, resistance, temperature, safety tier) are pass/fail gates.

CELLFEE checks **${R.applications.length} applications** from one registry${UB.skipped_applications.length ? `; skipped: ${UB.skipped_applications.map(a => a.name).join(', ')}` : ''}. Below ${UB.baselines.confidence.low_threshold_pct}% it advises a full test. ${UB.note}`)
  }

  return E
}

// ---------------------------------------------------------------- retrieval for typed questions
const STOP = new Set('a an the is are was were be to of in on for and or what whats how why does do did this that it its me my i you can with about explain tell show please which who where when there here'.split(' '))
const tokens = s => s.toLowerCase().replace(/[^a-z0-9.·±\s-]/g, ' ').split(/\s+/).filter(w => w && !STOP.has(w))

export function answer(KB, question, R) {
  const q = question.toLowerCase()
  // a specific battery?  "RB-07", "rb07", "battery 7"
  const m = q.match(/rb-?\s?(\d{1,4})/) || q.match(/battery\s+(\d{1,4})/)
  if (m && R) {
    const id = `RB-${String(+m[1]).padStart(4, '0')}`
    const b = R.fleet.find(x => x.id === id)
    if (b) return { title: `Battery ${id}`, text: `**${id}** (lab cell ${b.source_cell}, cycle ${b.cycle}, batch ${b.batch}): health **${pct(b.soh)}**, XGBoost **${pct(b.p_xgb)}**, AQSVC **${pct(b.p_aqsvc)}**${b.agree ? '' : ' (they disagree)'}, grade **${b.grade}**, decision **${b.action}**${b.pack ? ` in ${b.pack}` : ''}.\n\nOpen its passport on the Fleet & passports tab for the full reasons.` }
  }
  const tk = tokens(question)
  let best = null, bestScore = 0
  for (const e of Object.values(KB)) {
    let s = 0
    for (const k of e.keywords) if (q.includes(k)) s += k.includes(' ') ? 4 : 3
    const tw = tokens(e.title)
    for (const t of tk) if (tw.includes(t)) s += 1.5
    if (s > bestScore) { bestScore = s; best = e }
  }
  if (best && bestScore >= 3) return best
  return null
}

export const SUGGESTIONS = [
  'What is AQSVC?', 'Why run two models?', 'What is the quantum kernel?',
  'Why was a battery sent to test?', 'Is there a quantum advantage?', 'How do I upload test results?',
]
