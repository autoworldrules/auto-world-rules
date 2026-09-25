#!/usr/bin/env python3
import pickle
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

with open('auto-research/out/experiment_001/records.pkl', 'rb') as f:
    records = pickle.load(f)

# For each round N (1..10):
#   ET_0 on round N's eval:          records[N]['acc_et0_roundN_eval']
#   ET_{N} on round N's eval:        records[N]['acc_roundN_eval']
#   ET_{N-1} on round N's eval:      records[N-1]['acc_roundN+1_eval']

rounds = list(range(1, 11))
et0_acc = [records[n].get('acc_et0_roundN_eval', float('nan')) for n in rounds]
et_prev_acc = [records[n-1].get('acc_roundN+1_eval', float('nan')) for n in rounds]

# Annotations: what changed in each round's priority fn (< 10 words)
annotations = {
    1: "Baseline: return 0",
    2: "Score by entailed fact count",
    3: "+family relationship bonus",
    4: "+predicate diversity weighting",
    5: "+complex/gender-constraint scoring",
    6: "+entity connectivity density",
    7: "Reject not_living_in; +overlap scoring",
    8: "Filter self-ref; heavy multi-hop bonus",
    9: "Gender→multi-hop; stronger weights",
    10: "New entity pairs; hash noise",
}

fig, ax = plt.subplots(figsize=(14, 7))

ax.plot(rounds, et0_acc, 'o-', color='#2196F3', linewidth=2, markersize=8, label='ET_0 (baseline)')
ax.plot(rounds, et_prev_acc, 's-', color='#FF5722', linewidth=2, markersize=8, label='ET_{N-1} (prev round)')

# Annotate
for i, rnd in enumerate(rounds):
    txt = annotations[rnd]
    y_max = max(et0_acc[i], et_prev_acc[i])
    offset = 0.02 if i % 2 == 0 else -0.04
    ax.annotate(
        txt,
        xy=(rnd, y_max),
        xytext=(0, 14 if i % 2 == 0 else -18),
        textcoords='offset points',
        fontsize=7,
        ha='center',
        va='bottom' if i % 2 == 0 else 'top',
        rotation=25,
        bbox=dict(boxstyle='round,pad=0.2', facecolor='#FFF9C4', edgecolor='#BDBDBD', alpha=0.85),
        arrowprops=dict(arrowstyle='->', color='gray', lw=0.7),
    )

ax.set_xlabel('Round', fontsize=13)
ax.set_ylabel('Accuracy on Round N Eval', fontsize=13)
ax.set_title('ET_0 vs ET Trained on Previous Round — Accuracy on Each Round\'s Eval Set', fontsize=14)
ax.set_xticks(rounds)
ax.legend(fontsize=11, loc='upper right')
ax.grid(True, alpha=0.3)
ax.set_ylim(bottom=0)

plt.tight_layout()
plt.savefig('auto-research/out/experiment_001/rounds_accuracy_plot.png', dpi=150)
print("Saved to auto-research/out/experiment_001/rounds_accuracy_plot.png")
