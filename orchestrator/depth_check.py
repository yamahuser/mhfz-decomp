import json, sys
sys.path.insert(0, ".")
import feeder
feeder.index_new(); feeder.compute_depth()
from collections import Counter
c = Counter(feeder.depth.values())
print("reachable by depth:", dict(sorted(c.items())))
named_by_depth = Counter(feeder.depth.get(a, 99) for a in feeder.names)
print("named by depth:", dict(sorted(named_by_depth.items())))
print("reviewed:", len(feeder.reviewed), "(max", feeder.REVIEW_MAX, "depth<=", feeder.REVIEW_DEPTH, ")")
