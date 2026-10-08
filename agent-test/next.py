import json, sys, os
# python next.py <conv> <text|-> [yes|no]   (continues the conversation in out.txt)
conv, text = sys.argv[1], sys.argv[2]
confirm = sys.argv[3] if len(sys.argv) > 3 else None
st = fl = None
for line in open("out.txt", encoding="utf-8", errors="replace"):
    if line.startswith("STATE "): st = json.loads(line[6:])
    if line.startswith("FILES "): fl = json.loads(line[6:])
n = len([f for f in os.listdir(".") if f.startswith(conv + "_")])
os.replace("out.txt", f"{conv}_{n}.txt")
t = {"mode": "model", "conversation_id": conv, "messages": st["messages"], "files": fl}
if text != "-": t["text"] = text
if confirm: t["confirm"] = {"allow": confirm == "yes"}
json.dump(t, open("turn.json", "w", encoding="utf-8"), ensure_ascii=False)
print("turn", n + 1, "messages", len(st["messages"]))
