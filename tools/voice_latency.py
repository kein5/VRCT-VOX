"""Summarize timestamp-only measurements; never infer end-to-end audio latency."""
import argparse
import csv
import json
import math


def summarize(rows):
    groups = {}
    for row in rows:
        # Do not combine cold starts, GPU contention, OS or different boundaries.
        key = (row["metric"], row["environment"], row["warm"])
        value = (int(row["end_ns"]) - int(row["start_ns"])) / 1e6
        if value < 0:
            raise ValueError("Timestamps must share a monotonic clock and be ordered")
        groups.setdefault(key, []).append(value)
    result = []
    for (metric, environment, warm), values in sorted(groups.items()):
        values.sort()
        result.append({"metric": metric, "environment": environment, "warm": warm, "count": len(values),
                       **{f"p{p}_ms": values[math.ceil(len(values) * p / 100) - 1] for p in (50, 95, 99)}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="metric,environment,warm,start_ns,end_ns (no audio/text)")
    args = parser.parse_args()
    with open(args.csv, encoding="utf-8", newline="") as source:
        print(json.dumps(summarize(csv.DictReader(source)), indent=2))


if __name__ == "__main__":
    main()
