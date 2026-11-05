import json
from app.main import app

schema = app.openapi()
components = schema.get("components", {}).get("schemas", {})
wanted = [
    "PunchIn", "PunchOut",
    "DeviceCreateIn", "DeviceCreateOut",
    "DevicePatchIn", "DeviceOut",
    "DeviceRotateKeyOut", "DeviceListOut",
    "UserMeOut",
]
for name in wanted:
    if name not in components:
        print(f"===== {name} ===== MISSING")
        continue
    print(f"===== {name} =====")
    print(json.dumps(components[name], indent=2)[:3000])
    print()