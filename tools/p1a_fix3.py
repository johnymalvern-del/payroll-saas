"""Fix: use needsAck as a visible hint so it is not flagged unused."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "setup" / "IntelligenceSettingsPage.tsx"
s = P.read_text(encoding="utf-8")

# Insert a small hint after the SegmentedControl, gated by needsAck.
# Find the mode description Text block that already exists.
marker = '''          <Text size="sm" c="dimmed" data-testid="intel-mode-description">
            {MODE_DESCRIPTIONS[currentMode].description}
          </Text>
'''
if marker not in s:
    raise SystemExit("FATAL: mode description block not found")

hint = marker + '''          {needsAck && (
            <Alert color={colors.pending} data-testid="intel-ack-pending-hint">
              Click Save to acknowledge Autonomous mode.
            </Alert>
          )}
'''
s = s.replace(marker, hint, 1)
P.write_text(s, encoding="utf-8")
print("added needsAck hint alert")