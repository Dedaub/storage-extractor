#!/usr/bin/env python3
#!/usr/bin/env python3

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

df = pd.read_csv("benchmark_results.csv")

df_200 = df[df["Connections"] == 200]

plt.figure(figsize=(10, 6))
ax = sns.lineplot(
    data=df_200, x="Storage Lookups", y="Duration (s)", hue="Method", marker="o"
)
ax.grid(False)

plt.title("Duration vs Storage Lookups (200 Connections)")
plt.xlabel("Storage Lookups")
plt.xlim(left=1)
plt.ylabel("Duration (s)")
plt.yscale("log")
plt.legend(title="Method")
plt.tight_layout()
plt.savefig("./images/max_conns.png")


# Lets just see eth_call and batched since they're close
df_fast = df[df["Method"] != "Individual"]


# Setup the FacetGrid, using 'Connections' to create a subplot for each unique value
g = sns.FacetGrid(
    df_fast, col="Connections", col_wrap=3, height=4, sharex=True, sharey=True
)
g.map_dataframe(
    sns.lineplot,
    x="Storage Lookups",
    y="Duration (s)",
    hue="Method",
)
g.set_axis_labels("Number of Storage Lookups", "Duration (s)")
g.set_titles("Connections: {col_name}")

# Adjust x-axis for each subplot
for ax in g.axes:
    ax.set_xlim(left=1)

# Adding a legend outside the grid, at the bottom
g.fig.subplots_adjust(
    bottom=0.25, top=2, hspace=0.6
)  # Adjust the bottom to make space for the legend
g.add_legend(
    title="Method / Latency (ms)",
    bbox_to_anchor=(0.85, 0.25),
    loc="lower center",
    ncol=3,
)
g.fig.suptitle("Duration vs Storage Lookups for Varying Connections", fontsize=16)

plt.tight_layout()
plt.savefig("./images/comparison_grid.png")
