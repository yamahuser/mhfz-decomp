import json, sys
sys.path.insert(0, ".")
import feeder
for name in sys.argv[1:]:
    r = json.load(open(f"done_archive/{name}.json", encoding="utf-8"))
    print(name, r["backend"])
    try:
        print("  OK", feeder.parse_json(r["output"]))
    except Exception as e:
        print("  FAIL", e)
        print(repr(r["output"][:400]))
