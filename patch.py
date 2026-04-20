import re
path = "CommPlexCore/gcp/vertex.py"
with open(path, "r") as f: text = f.read()

patch = """
        if price is None:
            k_match = re.search(r'\\b(\\d{1,3}(?:\\.\\d)?)[kK]\\b', transcript)
            if k_match:
                price = float(k_match.group(1)) * 1000
"""

target = "        if price is None:\n            plain_match"
if target in text:
    with open(path, "w") as f:
        f.write(text.replace(target, patch + "\n" + target))
    print("✅ Patched vertex.py to understand '25k'!")
else:
    print("⚠️ Could not patch.")
