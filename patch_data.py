import os

patches = {
    "CommPlexCore/campaigns/mkz.py": [
        ("REPLACE_VIN_HERE", "3FA6P0LU0GRxxxxxx"), # Update with real VIN
        ("REPLACE_TARGET_PRICE", "14500")
    ],
    "CommPlexCore/campaigns/f350.py": [
        ("REPLACE_VIN_HERE", "1FTWW31R66Exxxxxx"),
        ("REPLACE_TARGET_PRICE", "22000")
    ]
}

for filepath, changes in patches.items():
    full_path = os.path.join(os.getcwd(), filepath)
    if os.path.exists(full_path):
        with open(full_path, 'r') as f:
            content = f.read()
        for old, new in changes:
            content = content.replace(old, new)
        with open(full_path, 'w') as f:
            f.write(content)
        print(f"✅ Patched {filepath}")

if __name__ == "__main__":
    print("🚀 Running Data Patch...")
