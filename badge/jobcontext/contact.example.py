"""Copy to contact.py and fill in — it's the screen saver's contact card.

contact.py is gitignored and copied onto the badge by badge/install.py. Every
field is optional except NAME; leave one empty ("") to hide it. Everything
here is shown to anyone who looks at your badge and is encoded in the QR code
anyone can scan — put only what you'd hand out on a business card.

Keep it short: the QR is a full vCard, and every character makes the code
denser and harder to scan off a 2.8" screen.
"""

NAME = "Your Name"
TITLE = "Senior Software Engineer"
EMAIL = "you@example.com"
PHONE = ""
LINKEDIN = "your-handle"   # linkedin.com/in/<this>
GITHUB = "your-handle"     # github.com/<this>
WEBSITE = ""               # e.g. "jobcontext.ai" (no https://)

# Seconds with no button presses before the card appears.
IDLE_SECONDS = 30
